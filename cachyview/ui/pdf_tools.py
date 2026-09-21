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


def _run_in_place(tab, label: str, fn: Callable) -> None:
    """Run *fn* on a worker thread and **replace the open file in place**.

    Used for lightweight, Preview-style edits (rotate / delete / insert) that
    should not spawn a new tab — the result is swapped into the current file
    and the view reloads.  *fn* receives a temp path; it must write there.
    """
    from ..core.safe import replace_in_place
    status = getattr(tab, "status", None)
    if status is not None:
        status.setText(f"{label}…")
    src = Path(tab.path)

    def work(ctx):
        def write(tmp: Path) -> None:
            fn(tmp, ctx)
        replace_in_place(src, write)

    job = submit(work, name=label)
    getattr(tab, "_jobs", []).append(job)
    if status is not None:
        job.signals.progress.connect(lambda _p, m: status.setText(m or label))
    job.signals.finished.connect(
        lambda _r: (tab.reload_from(src),
                    status.setText(f"{label} done") if status else None))
    job.signals.failed.connect(
        lambda msg, _t: QMessageBox.warning(tab, f"{label} failed", msg))
    return job


def run_tool(tab, name: str) -> None:
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
        from .image_resize import WatermarkDialog
        dialog = WatermarkDialog(tab)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        values = dialog.values()
        if not values.get("text") and not values.get("image"):
            return
        out = output_path(src, "watermarked")
        _run_job(tab, "Adding watermark",
                 lambda ctx: pb.watermark(
                     src, out, text=values.get("text"),
                     image=values.get("image"),
                     opacity=values.get("opacity", 0.15),
                     size=values.get("size", 48),
                     scale=values.get("scale", 0.4), password=pw),
                 lambda r: (_done_message(tab, r), tab.open_request.emit(str(r))))

    elif name == "Page numbers":
        out = output_path(src, "numbered")
        _run_job(tab, "Numbering pages",
                 lambda ctx: pb.add_page_numbers(src, out, password=pw),
                 lambda r: (_done_message(tab, r), tab.open_request.emit(str(r))))

    elif name == "Crop & Resize":
        from .pdf_margins import CropResizeDialog
        dialog = CropResizeDialog(tab)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        margins, size = dialog.chosen
        out = output_path(src, "cropped")
        _run_job(tab, "Cropping / resizing",
                 lambda ctx: pb.crop_resize_pages(
                     src, out, margins=margins, page_size=size, password=pw),
                 lambda r: (_done_message(tab, r), tab.open_request.emit(str(r))))

    elif name == "Invert colours":
        reply = QMessageBox.question(
            tab, "Invert colours",
            "Inverting renders each page to an image (dark-mode reading). "
            "The result is pixel-based, not vector. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        out = output_path(src, "inverted")
        _run_job(tab, "Inverting colours",
                 lambda ctx: pb.invert_colours(src, out, password=pw),
                 lambda r: (_done_message(tab, r), tab.open_request.emit(str(r))))

    elif name == "Headers & Footers":
        from .pdf_margins import HeaderFooterDialog
        dialog = HeaderFooterDialog(tab)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        header, footer, numbers, size = dialog.chosen
        out = output_path(src, "annotated")
        _run_job(tab, "Adding headers / footers",
                 lambda ctx: pb.add_headers_footers(
                     src, out, header=header, footer=footer,
                     page_numbers=numbers, size=size, password=pw),
                 lambda r: (_done_message(tab, r), tab.open_request.emit(str(r))))

    elif name == "Fingerprint":
        try:
            sums = pb.fingerprint(src)
        except OSError as exc:
            QMessageBox.warning(tab, "Fingerprint", str(exc))
            return
        QMessageBox.information(
            tab, "File fingerprint",
            f"{src.name}\n\nSHA-256: {sums['sha256']}\n"
            f"SHA-1:   {sums['sha1']}\nMD5:     {sums['md5']}")

    elif name == "Images to PDF…":
        from .image_to_pdf import ImageToPdfDialog
        ImageToPdfDialog(tab).exec()

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

    elif name == "N-up…":
        per, ok = QInputDialog.getItem(
            tab, "N-up", "Pages per sheet:", ["2", "4", "6", "9"], 0, False)
        if not ok:
            return
        out = output_path(src, f"nup-{per}")
        _run_job(tab, "Building N-up",
                 lambda ctx: pb.nup(src, out, per_sheet=int(per), password=pw),
                 lambda r: (_done_message(tab, r), tab.open_request.emit(str(r))))

    elif name == "Booklet…":
        out = output_path(src, "booklet")
        _run_job(tab, "Building booklet",
                 lambda ctx: pb.booklet(src, out, password=pw),
                 lambda r: (_done_message(tab, r), tab.open_request.emit(str(r))))

    elif name == "Linearize":
        out = output_path(src, "linearized")
        _run_job(tab, "Linearizing",
                 lambda ctx: pb.linearize(src, out, password=pw),
                 lambda r: _done_message(tab, r))

    elif name == "To HTML":
        out = output_path(src, "html", ".html")
        _run_job(tab, "Exporting HTML",
                 lambda ctx: pb.to_html(src, out, password=pw),
                 lambda r: (_done_message(tab, r), tab.open_request.emit(str(r))))

    elif name == "To Word (.docx)":
        dest = QFileDialog.getExistingDirectory(
            tab, "Save Word document to", str(src.parent))
        if not dest:
            return
        _run_job(tab, "Converting to Word",
                 lambda ctx: pb.to_docx(src, dest, password=pw, ctx=ctx),
                 lambda r: _done_message(tab, r))

    elif name == "To PDF/A":
        level, ok = QInputDialog.getItem(
            tab, "PDF/A", "Conformance level:",
            ["PDF/A-1", "PDF/A-2", "PDF/A-3"], 1, False)
        if not ok:
            return
        out = output_path(src, f"pdfa-{level[-1]}")
        _run_job(tab, "Converting to PDF/A",
                 lambda ctx: pb.to_pdfa(src, out, level=int(level[-1]),
                                        password=pw),
                 lambda r: (_done_message(tab, r), tab.open_request.emit(str(r))))

    elif name == "Text / Markdown to PDF…":
        files, _ = QFileDialog.getOpenFileNames(
            tab, "Select text/Markdown files", str(src.parent),
            "Text (*.txt *.md *.markdown)")
        if not files:
            return
        dest = QFileDialog.getExistingDirectory(
            tab, "Save PDFs to", str(src.parent))
        if not dest:
            return

        def _typeset(_ctx):
            made = []
            for f in files:
                target = Path(dest) / (Path(f).stem + ".pdf")
                made.append(pb.text_to_pdf(f, target))
            return made

        _run_job(tab, "Typesetting", _typeset,
                 lambda made: QMessageBox.information(
                     tab, "Finished", f"Wrote {len(made)} PDF(s) to:\n{dest}"))

    elif name == "Metadata":
        current = tab.info.metadata if tab.info else {}
        values = {}
        for key, label in (("title", "Title"), ("author", "Author"),
                           ("subject", "Subject"), ("keywords", "Keywords")):
            text, ok = QInputDialog.getText(
                tab, "Metadata", f"{label}:", QLineEdit.EchoMode.Normal,
                current.get(key, ""))
            if not ok:
                return
            values[key] = text
        out = output_path(src, "metadata")
        _run_job(tab, "Writing metadata",
                 lambda ctx: pb.set_metadata(src, out, values, password=pw),
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

    elif name == "Fill form…":
        try:
            fields = pb.list_form_fields(src, pw)
        except pb.PdfError as exc:
            QMessageBox.warning(tab, "Form", str(exc))
            return
        if not fields:
            QMessageBox.information(tab, "Form", "This PDF has no fillable fields.")
            return
        values = {}
        for field in fields:
            text, ok = QInputDialog.getText(
                tab, "Fill form",
                f"{field['name']} (page {field['page']}):",
                text=field["value"])
            if not ok:
                return
            values[field["name"]] = text
        out = output_path(src, "filled")
        _run_job(tab, "Filling form",
                 lambda ctx: pb.fill_form_fields(src, out, values, password=pw),
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
