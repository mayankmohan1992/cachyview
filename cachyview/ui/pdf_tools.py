"""Dialogs that drive the PDF backend from the viewer's Tools menu.

Each tool collects its parameters, then runs the backend call on a worker
thread so a slow operation (OCR, compression) never freezes the window.
Output is written next to the source with a descriptive suffix, so the
original file is never overwritten in place.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from PyQt6.QtWidgets import (QFileDialog, QInputDialog, QLineEdit, QMessageBox,
                             QWidget)

from ..backends import pdf as pb
from ..core.jobs import submit


def output_path(src: Path, suffix: str, ext: str = ".pdf") -> Path:
    """A non-clobbering sibling path like ``report-compressed.pdf``."""
    target = src.with_name(f"{src.stem}-{suffix}{ext}")
    n = 2
    while target.exists():
        target = src.with_name(f"{src.stem}-{suffix}-{n}{ext}")
        n += 1
    return target


def _run_job(tab: QWidget, label: str, fn: Callable, on_done: Callable) -> None:
    """Run *fn* on a worker thread, reporting progress on the tab's status bar."""
    status = getattr(tab, "status", None)
    if status is not None:
        status.setText(f"{label}…")

    job = submit(fn, name=label)
    getattr(tab, "_jobs", []).append(job)
    if status is not None:
        job.signals.progress.connect(lambda _p, m: status.setText(m or label))
    job.signals.finished.connect(on_done)
    job.signals.failed.connect(
        lambda msg, _t: QMessageBox.warning(tab, f"{label} failed", msg))


def _done_message(tab: QWidget, target: Path, extra: str = "") -> None:
    status = getattr(tab, "status", None)
    if status is not None:
        status.setText(f"Wrote {target.name}{extra}")
    QMessageBox.information(
        tab, "Finished", f"Saved to:\n{target}{extra}")


def run_tool(tab, name: str) -> None:      # noqa: C901 - a dispatch table
    """Execute the named tool against ``tab.path``."""
    src: Path = tab.path
    pw = tab.password

    if name == "Organise pages…":
        from .page_organiser import PageOrganiser
        dialog = PageOrganiser(src, pw, tab)
        if dialog.exec() and dialog.result_path is not None:
            _done_message(tab, dialog.result_path)
        return
    total = tab.info.page_count if tab.info else 0

    def ranges_prompt(title: str, default: str = "") -> str | None:
        text, ok = QInputDialog.getText(
            tab, title, f"Pages (e.g. 1-3,5) of 1-{total}:",
            QLineEdit.EchoMode.Normal, default)
        return text.strip() if ok else None

    if name == "Rotate pages":
        angle, ok = QInputDialog.getItem(
            tab, "Rotate pages", "Rotate by:", ["90", "180", "270"], 0, False)
        if not ok:
            return
        rng = ranges_prompt("Rotate pages", "")
        if rng is None:
            return
        out = output_path(src, "rotated")
        _run_job(tab, "Rotating",
                 lambda ctx: pb.rotate_pages(src, out, angle=int(angle),
                                             ranges=rng or None, password=pw),
                 lambda r: (_done_message(tab, r), tab.open_request.emit(str(r))))

    elif name == "Delete pages":
        rng = ranges_prompt("Delete pages")
        if not rng:
            return
        out = output_path(src, "trimmed")
        _run_job(tab, "Deleting pages",
                 lambda ctx: pb.delete_pages(src, out, rng, password=pw),
                 lambda r: (_done_message(tab, r), tab.open_request.emit(str(r))))

    elif name == "Extract pages":
        rng = ranges_prompt("Extract pages")
        if not rng:
            return
        out = output_path(src, "extract")
        _run_job(tab, "Extracting pages",
                 lambda ctx: pb.extract_pages(src, out, rng, password=pw),
                 lambda r: (_done_message(tab, r), tab.open_request.emit(str(r))))

    elif name == "Split":
        every, ok = QInputDialog.getInt(
            tab, "Split", "Pages per file:", 1, 1, max(1, total))
        if not ok:
            return
        dest = QFileDialog.getExistingDirectory(tab, "Save parts to", str(src.parent))
        if not dest:
            return
        _run_job(tab, "Splitting",
                 lambda ctx: pb.split(src, dest, every=every, password=pw, ctx=ctx),
                 lambda parts: QMessageBox.information(
                     tab, "Finished", f"Wrote {len(parts)} file(s) to:\n{dest}"))

    elif name == "Merge with…":
        others, _ = QFileDialog.getOpenFileNames(
            tab, "Select PDFs to append", str(src.parent), "PDF files (*.pdf)")
        if not others:
            return
        out = output_path(src, "merged")
        _run_job(tab, "Merging",
                 lambda ctx: pb.merge([src] + [Path(o) for o in others], out, ctx=ctx),
                 lambda r: (_done_message(tab, r), tab.open_request.emit(str(r))))

    elif name == "Compress":
        tier, ok = QInputDialog.getItem(
            tab, "Compress", "Quality:",
            ["screen (smallest)", "ebook (balanced)", "printer", "prepress"],
            1, False)
        if not ok:
            return
        key = tier.split()[0]
        out = output_path(src, "compressed")

        def done(result):
            path, before, after = result
            if after < before:
                saved = 100 - (after * 100 // max(1, before))
                detail = (f"\n{before // 1024} KB → {after // 1024} KB "
                          f"({saved}% smaller)")
            else:
                detail = (f"\n{before // 1024} KB → {after // 1024} KB"
                          "\nNo reduction: this PDF was already compact.")
            _done_message(tab, path, detail)

        _run_job(tab, "Compressing",
                 lambda ctx: pb.compress(src, out, tier=key, password=pw, ctx=ctx),
                 done)

    elif name == "Flatten":
        reply = QMessageBox.question(
            tab, "Flatten",
            "Flattening bakes annotations and form fields into the page so they "
            "can no longer be edited or removed. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        out = output_path(src, "flattened")

        def done(result):
            _done_message(tab, result)

        _run_job(tab, "Flattening",
                 lambda ctx: pb.flatten(src, out, password=pw), done)

    elif name == "Protect":
        pwd, ok = QInputDialog.getText(
            tab, "Protect", "New password:", QLineEdit.EchoMode.Password)
        if not ok or not pwd:
            return
        out = output_path(src, "protected")
        _run_job(tab, "Encrypting",
                 lambda ctx: pb.protect(src, out, user_password=pwd, password=pw),
                 lambda r: _done_message(tab, r))

    elif name == "Unlock":
        pwd, ok = QInputDialog.getText(
            tab, "Unlock", "Current password:", QLineEdit.EchoMode.Password)
        if not ok or not pwd:
            return
        out = output_path(src, "unlocked")
        _run_job(tab, "Removing protection",
                 lambda ctx: pb.unlock(src, out, password=pwd),
                 lambda r: (_done_message(tab, r), tab.open_request.emit(str(r))))

    elif name == "Watermark":
        text, ok = QInputDialog.getText(tab, "Watermark", "Watermark text:")
        if not ok or not text.strip():
            return
        out = output_path(src, "watermarked")
        _run_job(tab, "Adding watermark",
                 lambda ctx: pb.watermark(src, out, text=text.strip(), password=pw),
                 lambda r: (_done_message(tab, r), tab.open_request.emit(str(r))))

    elif name == "Page numbers":
        out = output_path(src, "numbered")
        _run_job(tab, "Numbering pages",
                 lambda ctx: pb.add_page_numbers(src, out, password=pw),
                 lambda r: (_done_message(tab, r), tab.open_request.emit(str(r))))

    elif name == "To images":
        dpi, ok = QInputDialog.getInt(tab, "To images", "Resolution (DPI):",
                                      150, 36, 600)
        if not ok:
            return
        dest = QFileDialog.getExistingDirectory(tab, "Save images to", str(src.parent))
        if not dest:
            return
        _run_job(tab, "Rendering pages",
                 lambda ctx: pb.to_images(src, dest, dpi=dpi, password=pw, ctx=ctx),
                 lambda files: QMessageBox.information(
                     tab, "Finished", f"Wrote {len(files)} image(s) to:\n{dest}"))

    elif name == "To text":
        out = output_path(src, "text", ".txt")
        _run_job(tab, "Extracting text",
                 lambda ctx: pb.to_text_file(src, out, password=pw),
                 lambda r: (_done_message(tab, r), tab.open_request.emit(str(r))))

    elif name == "OCR":
        lang, ok = QInputDialog.getText(
            tab, "OCR", "Language code (e.g. eng, deu, hin):",
            QLineEdit.EchoMode.Normal, "eng")
        if not ok or not lang.strip():
            return
        out = output_path(src, "ocr")
        _run_job(tab, "Running OCR",
                 lambda ctx: pb.ocr(src, out, language=lang.strip(), ctx=ctx),
                 lambda r: (_done_message(tab, r), tab.open_request.emit(str(r))))

    elif name == "Repair":
        out = output_path(src, "repaired")
        _run_job(tab, "Repairing",
                 lambda ctx: pb.repair(src, out, password=pw),
                 lambda r: (_done_message(tab, r), tab.open_request.emit(str(r))))

    elif name == "Metadata":
        current = tab.info.metadata if tab.info else {}
        title, ok = QInputDialog.getText(
            tab, "Metadata", "Title:", QLineEdit.EchoMode.Normal,
            current.get("title", ""))
        if not ok:
            return
        author, ok = QInputDialog.getText(
            tab, "Metadata", "Author:", QLineEdit.EchoMode.Normal,
            current.get("author", ""))
        if not ok:
            return
        out = output_path(src, "metadata")
        _run_job(tab, "Writing metadata",
                 lambda ctx: pb.set_metadata(src, out,
                                             {"title": title, "author": author},
                                             password=pw),
                 lambda r: (_done_message(tab, r), tab.open_request.emit(str(r))))

    elif name == "Sign / Stamp":
        img, _ = QFileDialog.getOpenFileName(
            tab, "Signature image (optional)", "",
            "Images (*.png *.jpg *.jpeg *.pdf)")
        text, ok = QInputDialog.getText(
            tab, "Stamp text", "Caption to print (optional):")
        if not ok:
            return
        out = output_path(src, "stamped")
        _run_job(tab, "Stamping",
                 lambda ctx: pb.stamp(src, out, image=img or None,
                                     text=text or None, password=pw),
                 lambda r: (_done_message(tab, r), tab.open_request.emit(str(r))))

    elif name == "Redact…":
        QMessageBox.information(
            tab, "Redact",
            "Use the Annotate ▸ Redact (permanent) tool on the toolbar, then "
            "drag a box over the content to remove it permanently.")

    elif name == "Bookmarks…":
        from .outline_dialog import OutlineDialog
        dialog = OutlineDialog(src, password=pw, parent=tab)
        dialog.exec()
