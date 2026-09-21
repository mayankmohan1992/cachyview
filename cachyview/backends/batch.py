"""Batch processing: run a chain of operations over many files.

A *job* is a list of operations plus a list of input files.  Each operation is
a string the matching backend understands (e.g. ``{"tool": "compress",
"tier": "ebook"}`` for PDFs, ``{"tool": "rotate", "angle": 90}`` for images).
The queue runs them sequentially on a worker thread, reporting per-file
progress and a final summary, and never throws past a single file — a failure
marks that item and continues.

This deliberately reuses the existing backends (``cachyview.backends.pdf`` and
``.image``), so a batch of 500 files uses the very same lossless paths a
single-file tool would.
"""
from __future__ import annotations

import shutil
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..core.jobs import JobContext, make_job, start_job
from ..core.safe import safe_backup_path
from . import image as ib
from . import pdf as pb

DEFAULT_TIMEOUT = pb.DEFAULT_TIMEOUT


@dataclass
class BatchItem:
    """One input file and its outcome."""
    source: Path
    output: Path | None = None
    status: str = "pending"     # pending | running | done | failed | skipped
    message: str = ""
    trace: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "done"


@dataclass
class BatchJob:
    """A named batch with inputs, operations and per-item results."""
    name: str
    operations: list[dict[str, Any]]
    items: list[BatchItem] = field(default_factory=list)
    # Set by the caller to choose where output goes; None = alongside input.
    output_dir: Path | None = None
    # When overwriting a file in place, keep a ``name~`` recoverable copy.
    backup: bool = True
    # Optional output-name pattern: {name}/{stem}, {ext}, {n}.
    rename_pattern: str | None = None
    # Preserve EXIF metadata on image saves.
    keep_exif: bool = True

    def add_file(self, path: str | Path) -> None:
        self.items.append(BatchItem(source=Path(path)))


def _route(operations: list[dict[str, Any]], src: Path, dest: Path,
           ctx: JobContext | None, *, keep_exif: bool = True) -> None:
    """Apply every operation to *src*, writing the final result to *dest*."""
    suffix = src.suffix.lower()
    is_pdf = suffix == ".pdf"
    is_image = suffix in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp",
                          ".tif", ".tiff", ".avif", ".heic")

    if not (is_pdf or is_image):
        raise ValueError(f"Unsupported file type: {src.name}")

    stage = src
    try:
        for op in operations:
            tool = op.get("tool", "")
            if is_pdf:
                stage = _pdf_op(tool, op, stage, ctx)
            else:
                stage = _image_op(tool, op, stage, ctx, keep_exif)
        if Path(stage).resolve() != dest.resolve():
            shutil.move(str(stage), str(dest))
    finally:
        if Path(stage).resolve() not in (src.resolve(), dest.resolve()):
            Path(stage).unlink(missing_ok=True)


def _pdf_op(tool: str, op: dict[str, Any], stage: Path,
            ctx: JobContext | None) -> Path:
    opts = dict(op)
    opts.pop("tool", None)
    if tool == "compress":
        out = stage.with_name(f".batch-{stage.stem}.pdf")
        result, _, _ = pb.compress(stage, out, tier=opts.get("tier", "ebook"),
                                    ctx=ctx)
        return result
    if tool == "rotate":
        out = stage.with_name(f".batch-{stage.stem}.pdf")
        return pb.rotate_pages(stage, out, angle=int(opts.get("angle", 90)),
                               password=opts.get("password"))
    if tool == "ocr":
        out = stage.with_name(f".batch-{stage.stem}.pdf")
        return pb.ocr(stage, out, language=opts.get("language", "eng"),
                      ctx=ctx)
    if tool == "watermark":
        out = stage.with_name(f".batch-{stage.stem}.pdf")
        return pb.watermark(stage, out, text=opts.get("text", "CachyView"),
                            ctx=ctx)
    if tool == "to_images":
        out_dir = stage.parent / f"{stage.stem}-pages"
        pb.to_images(stage, out_dir, dpi=int(opts.get("dpi", 150)),
                     fmt=opts.get("fmt", "png"), ctx=ctx)
        return out_dir
    raise ValueError(f"Unknown PDF batch operation: {tool}")


def _image_op(tool: str, op: dict[str, Any], stage: Path,
              ctx: JobContext | None, keep_exif: bool = True) -> Path:
    opts = dict(op)
    opts.pop("tool", None)
    img = ib.load(stage)
    if tool == "rotate":
        img = ib.apply_ops(img,
                           [ib.Op("rotate", {"angle": int(opts.get("angle", 90))})],
                           ctx=ctx)
        out = stage.with_name(f".batch-{stage.stem}{stage.suffix}")
        return ib.save(img, out, source=img, keep_exif=keep_exif)
    if tool == "grayscale":
        img = ib.apply_ops(img, [ib.Op("grayscale")], ctx=ctx)
        out = stage.with_name(f".batch-{stage.stem}{stage.suffix}")
        return ib.save(img, out, source=img, keep_exif=keep_exif)
    if tool == "resize":
        if opts.get("factor"):
            img = ib.apply_ops(img, [ib.Op("scale", {"factor": float(opts["factor"])})],
                               ctx=ctx)
        else:
            img = ib.apply_ops(img,
                               [ib.Op("resize", {"width": int(opts.get("width") or 0) or None,
                                                  "height": int(opts.get("height") or 0) or None})],
                               ctx=ctx)
        out = stage.with_name(f".batch-{stage.stem}{stage.suffix}")
        return ib.save(img, out, source=img, keep_exif=keep_exif)
    if tool == "scale":
        img = ib.apply_ops(img,
                           [ib.Op("scale", {"factor": float(opts.get("factor", 0.5))})],
                           ctx=ctx)
        out = stage.with_name(f".batch-{stage.stem}{stage.suffix}")
        return ib.save(img, out, source=img, keep_exif=keep_exif)
    if tool == "ops":
        ops = [ib.Op(o["name"], o.get("args") or {}) for o in opts.get("chain", [])]
        img = ib.apply_ops(img, ops, ctx=ctx)
        out = stage.with_name(f".batch-{stage.stem}{stage.suffix}")
        keep = opts.get("keep_exif", keep_exif)
        return ib.save(img, out, source=img, keep_exif=keep)
    if tool == "convert":
        fmt = opts.get("format", "png").lower()
        ext = ".jpg" if fmt == "jpeg" else f".{fmt}"
        out = stage.with_name(f"{stage.stem}{ext}")
        return ib.save(img, out, source=img, keep_exif=keep_exif)
    raise ValueError(f"Unknown image batch operation: {tool}")


def run_batch(job: BatchJob, on_item: Callable[[BatchItem], None] | None = None,
              ctx: JobContext | None = None) -> BatchJob:
    """Process every item, updating status as it goes. Returns the job."""
    for index, item in enumerate(job.items, start=1):
        if item.status in ("done", "failed", "running"):
            continue
        item.status = "running"
        if on_item is not None:
            on_item(item)
        dest = _destination(job, item.source, index)
        try:
            if ctx is not None:
                ctx.progress(-1, f"{item.source.name}")
            if (job.output_dir is None and job.backup
                    and dest.resolve() == item.source.resolve()
                    and item.source.exists()):
                # Preserve the original before an in-place overwrite so a bad
                # operation is always recoverable (mirrors replace_in_place).
                backup = safe_backup_path(item.source)
                backup.unlink(missing_ok=True)
                shutil.copy2(item.source, backup)
            _route(job.operations, item.source, dest, ctx,
                   keep_exif=job.keep_exif)
            item.output = dest
            item.status = "done"
            item.message = "OK"
        except Exception as exc:
            item.status = "failed"
            item.message = f"{type(exc).__name__}: {exc}"
            item.trace = traceback.format_exc()
        if on_item is not None:
            on_item(item)
    return job


def _rename(src: Path, pattern: str | None, index: int) -> str:
    """Apply a ``{name}/{stem}/{ext}/{n}`` pattern; keep the suffix if omitted."""
    if not pattern:
        return src.name
    name = (pattern.replace("{name}", src.stem)
            .replace("{stem}", src.stem)
            .replace("{ext}", src.suffix)
            .replace("{n}", str(index)))
    name = name.strip() or src.name
    if not Path(name).suffix:
        name += src.suffix
    return name


def _destination(job: BatchJob, src: Path, index: int = 1) -> Path:
    if job.output_dir is not None:
        job.output_dir.mkdir(parents=True, exist_ok=True)
        return job.output_dir / _rename(src, job.rename_pattern, index)
    if job.rename_pattern:
        return src.with_name(_rename(src, job.rename_pattern, index))
    return src  # in place; _route lands the final stage here


def run_batch_async(job: BatchJob, on_item=None) -> Any:
    """Run :func:`run_batch` on a worker thread; returns the job handle.

    ``on_item`` (if given) is invoked on the GUI thread for every item update;
    the worker emits it through a queued signal so it is safe to touch widgets.
    """
    ref: list[Any] = []

    def work(ctx):
        emit = None if on_item is None else ref[0].signals.item.emit
        return run_batch(job, on_item=emit, ctx=ctx)

    handle = make_job(work, name=job.name)
    ref.append(handle)
    if on_item is not None:
        handle.signals.item.connect(on_item)
    return start_job(handle)
