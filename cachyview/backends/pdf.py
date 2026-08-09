"""PDF backend: render, reorganise, convert, secure and OCR PDF files.

Tool selection follows one rule: never re-render when a lossless path exists.

* **pikepdf/qpdf** - merge, split, rotate, delete, reorder, encrypt, repair.
  These rewrite the file structure, leaving page content streams untouched.
* **PyMuPDF** - rasterising for display, text extraction, watermarks, redaction.
* **Ghostscript** - the compression tiers, which necessarily re-encode.
* **ocrmypdf** - adds a searchable text layer to scans.

Page numbers are **1-based** in every public function, matching what the user
sees; the 0-based indexing of the libraries is confined to this module.
"""
from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from ..core.process import run as run_tool

DEFAULT_TIMEOUT = 600


class PdfError(Exception):
    """A PDF operation failed."""


class PdfPasswordRequired(PdfError):
    """The document is encrypted and needs a password to open."""


class PdfWrongPassword(PdfPasswordRequired):
    """A password was supplied but rejected."""


@dataclass
class PageInfo:
    """Geometry of a single page."""

    number: int          # 1-based
    width: float         # points
    height: float
    rotation: int = 0

    @property
    def is_landscape(self) -> bool:
        return self.width > self.height

    @property
    def size_mm(self) -> tuple[float, float]:
        return (self.width * 25.4 / 72, self.height * 25.4 / 72)


@dataclass
class PdfInfo:
    """Summary of a PDF document."""

    path: Path
    page_count: int
    encrypted: bool = False
    pages: list[PageInfo] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)
    file_size: int = 0
    has_text: bool = False
    toc: list[tuple[int, str, int]] = field(default_factory=list)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _fitz():
    try:
        import fitz
        return fitz
    except ImportError as exc:      # pragma: no cover - dependency is installed
        raise PdfError("PDF support needs the 'python-pymupdf' package.") from exc


def _pikepdf():
    try:
        import pikepdf
        return pikepdf
    except ImportError as exc:      # pragma: no cover
        raise PdfError("This tool needs the 'python-pikepdf' package.") from exc


def open_doc(path: str | os.PathLike, password: str | None = None):
    """Open a PDF with PyMuPDF, translating auth failures into our exceptions."""
    fitz = _fitz()
    p = Path(path)
    if not p.is_file():
        raise PdfError(f"No such file: {p}")
    try:
        doc = fitz.open(p)
    except Exception as exc:
        raise PdfError(f"Cannot open {p.name}: {exc}") from exc
    if doc.needs_pass:
        if password is None:
            doc.close()
            raise PdfPasswordRequired("This PDF is password protected.")
        if not doc.authenticate(password):
            doc.close()
            raise PdfWrongPassword("Incorrect password.")
    return doc


def parse_ranges(spec: str, page_count: int) -> list[int]:
    """Turn ``"1-3,7,9-"`` into a sorted list of 1-based page numbers.

    Raises :class:`PdfError` when the spec is malformed or out of range.
    """
    if not spec or not spec.strip():
        return list(range(1, page_count + 1))

    pages: set[int] = set()
    for chunk in spec.replace(" ", "").split(","):
        if not chunk:
            continue
        if not re.fullmatch(r"\d*-?\d*", chunk) or chunk == "-":
            raise PdfError(f"Invalid page range: {chunk!r}")
        if "-" in chunk:
            start_s, end_s = chunk.split("-", 1)
            start = int(start_s) if start_s else 1
            end = int(end_s) if end_s else page_count
        else:
            start = end = int(chunk)
        if start < 1 or end > page_count or start > end:
            raise PdfError(
                f"Page range {chunk!r} is outside 1-{page_count}.")
        pages.update(range(start, end + 1))
    if not pages:
        raise PdfError("No pages selected.")
    return sorted(pages)


def _require(tool: str, package: str) -> str:
    found = shutil.which(tool)
    if not found:
        raise PdfError(f"This needs the '{package}' package ({tool} not found).")
    return found


# --------------------------------------------------------------------------
# inspection
# --------------------------------------------------------------------------

def info(path: str | os.PathLike, password: str | None = None) -> PdfInfo:
    """Read page geometry, metadata and the table of contents."""
    p = Path(path)
    doc = open_doc(p, password)
    try:
        pages = [
            PageInfo(number=i + 1, width=pg.rect.width, height=pg.rect.height,
                     rotation=pg.rotation)
            for i, pg in enumerate(doc)
        ]
        meta = {k: str(v) for k, v in (doc.metadata or {}).items() if v}
        has_text = any(doc[i].get_text().strip()
                       for i in range(min(5, doc.page_count)))
        try:
            toc = [(lvl, title, page) for lvl, title, page in doc.get_toc()]
        except Exception:
            toc = []
        return PdfInfo(
            path=p, page_count=doc.page_count, encrypted=doc.needs_pass,
            pages=pages, metadata=meta, file_size=p.stat().st_size,
            has_text=has_text, toc=toc,
        )
    finally:
        doc.close()


def render_page(path: str | os.PathLike, page: int, *, dpi: int = 150,
                password: str | None = None) -> bytes:
    """Rasterise one 1-based page to PNG bytes."""
    doc = open_doc(path, password)
    try:
        if not 1 <= page <= doc.page_count:
            raise PdfError(f"Page {page} is outside 1-{doc.page_count}.")
        pix = doc[page - 1].get_pixmap(dpi=dpi)
        return pix.tobytes("png")
    finally:
        doc.close()


def extract_text(path: str | os.PathLike, pages: Iterable[int] | None = None,
                 password: str | None = None) -> str:
    """Extract the text layer.  Returns "" for scans with no text."""
    doc = open_doc(path, password)
    try:
        wanted = list(pages) if pages else range(1, doc.page_count + 1)
        return "\n".join(doc[n - 1].get_text() for n in wanted
                         if 1 <= n <= doc.page_count)
    finally:
        doc.close()


# --------------------------------------------------------------------------
# structural operations (lossless, via pikepdf)
# --------------------------------------------------------------------------

def merge(sources: list[str | os.PathLike], dest: str | os.PathLike,
          passwords: dict[str, str] | None = None, *, ctx=None) -> Path:
    """Concatenate PDFs in the given order."""
    pikepdf = _pikepdf()
    if not sources:
        raise PdfError("No files to merge.")
    out = Path(dest)
    pw = passwords or {}
    try:
        with pikepdf.Pdf.new() as target:
            for i, src in enumerate(sources):
                s = Path(src)
                try:
                    with pikepdf.open(s, password=pw.get(str(s), "")) as doc:
                        target.pages.extend(doc.pages)
                except pikepdf.PasswordError as exc:
                    raise PdfPasswordRequired(
                        f"{s.name} is password protected.") from exc
                if ctx is not None:
                    ctx.progress(int((i + 1) / len(sources) * 100), f"Added {s.name}")
            target.save(out)
    except pikepdf.PdfError as exc:
        raise PdfError(f"Merge failed: {exc}") from exc
    return out


def split(path: str | os.PathLike, dest_dir: str | os.PathLike, *,
          every: int = 1, ranges: str | None = None,
          password: str | None = None, ctx=None) -> list[Path]:
    """Split into chunks of *every* pages, or into one file per *ranges* group."""
    pikepdf = _pikepdf()
    src = Path(path)
    out_dir = Path(dest_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    try:
        with pikepdf.open(src, password=password or "") as doc:
            total = len(doc.pages)
            if ranges:
                groups = [parse_ranges(chunk, total)
                          for chunk in ranges.split(";") if chunk.strip()]
            else:
                if every < 1:
                    raise PdfError("Split size must be at least 1 page.")
                groups = [list(range(i + 1, min(i + every, total) + 1))
                          for i in range(0, total, every)]

            for idx, group in enumerate(groups, start=1):
                with pikepdf.Pdf.new() as part:
                    for n in group:
                        part.pages.append(doc.pages[n - 1])
                    target = out_dir / f"{src.stem}-{idx:03d}.pdf"
                    part.save(target)
                    written.append(target)
                if ctx is not None:
                    ctx.progress(int(idx / len(groups) * 100), f"Wrote {target.name}")
    except pikepdf.PasswordError as exc:
        raise PdfPasswordRequired("This PDF is password protected.") from exc
    except pikepdf.PdfError as exc:
        raise PdfError(f"Split failed: {exc}") from exc
    return written


def extract_pages(path: str | os.PathLike, dest: str | os.PathLike,
                  ranges: str, password: str | None = None) -> Path:
    """Write a new PDF containing only the pages named by *ranges*."""
    pikepdf = _pikepdf()
    src, out = Path(path), Path(dest)
    try:
        with pikepdf.open(src, password=password or "") as doc:
            wanted = parse_ranges(ranges, len(doc.pages))
            with pikepdf.Pdf.new() as part:
                for n in wanted:
                    part.pages.append(doc.pages[n - 1])
                part.save(out)
    except pikepdf.PasswordError as exc:
        raise PdfPasswordRequired("This PDF is password protected.") from exc
    return out


def delete_pages(path: str | os.PathLike, dest: str | os.PathLike,
                 ranges: str, password: str | None = None) -> Path:
    """Write a copy without the pages named by *ranges*."""
    pikepdf = _pikepdf()
    src, out = Path(path), Path(dest)
    with pikepdf.open(src, password=password or "") as doc:
        drop = set(parse_ranges(ranges, len(doc.pages)))
        keep = [n for n in range(1, len(doc.pages) + 1) if n not in drop]
        if not keep:
            raise PdfError("Refusing to delete every page.")
        with pikepdf.Pdf.new() as part:
            for n in keep:
                part.pages.append(doc.pages[n - 1])
            part.save(out)
    return out


def rotate_pages(path: str | os.PathLike, dest: str | os.PathLike, *,
                 angle: int = 90, ranges: str | None = None,
                 password: str | None = None) -> Path:
    """Rotate pages by a multiple of 90 degrees, relative to their current angle."""
    if angle % 90:
        raise PdfError("Rotation must be a multiple of 90 degrees.")
    pikepdf = _pikepdf()
    src, out = Path(path), Path(dest)
    with pikepdf.open(src, password=password or "") as doc:
        wanted = parse_ranges(ranges or "", len(doc.pages))
        for n in wanted:
            page = doc.pages[n - 1]
            current = int(page.get("/Rotate", 0) or 0)
            page.Rotate = (current + angle) % 360
        doc.save(out)
    return out


def apply_layout(path: str | os.PathLike, dest: str | os.PathLike,
                 layout: list[tuple[int, int]],
                 password: str | None = None) -> Path:
    """Rebuild a document from an arbitrary page layout.

    *layout* is a list of ``(source_page, rotation)`` pairs, where
    ``source_page`` is 1-based and ``rotation`` is an absolute angle in
    degrees.  Unlike :func:`reorder_pages` this is not restricted to a
    permutation: a page may be repeated (duplicate), omitted (delete) or
    reordered, which is what the page organiser needs.

    Pages are copied structurally, so text stays selectable and nothing is
    re-rendered.
    """
    pikepdf = _pikepdf()
    src, out = Path(path), Path(dest)
    if not layout:
        raise PdfError("The document must keep at least one page.")

    with pikepdf.open(src, password=password or "") as doc:
        total = len(doc.pages)
        for source, _ in layout:
            if not 1 <= source <= total:
                raise PdfError(f"Page {source} is outside this {total}-page document.")

        with pikepdf.Pdf.new() as part:
            for source, rotation in layout:
                # copy_foreign-free: appending the same page twice needs a copy
                part.pages.append(doc.pages[source - 1])
                page = part.pages[len(part.pages) - 1]
                angle = int(rotation) % 360
                if angle:
                    page.Rotate = angle
                elif "/Rotate" in page:
                    del page.Rotate
            part.remove_unreferenced_resources()
            part.save(out)
    return out


def reorder_pages(path: str | os.PathLike, dest: str | os.PathLike,
                  order: list[int], password: str | None = None) -> Path:
    """Rewrite the document with pages in the given 1-based *order*."""
    pikepdf = _pikepdf()
    src, out = Path(path), Path(dest)
    with pikepdf.open(src, password=password or "") as doc:
        total = len(doc.pages)
        if sorted(order) != list(range(1, total + 1)):
            raise PdfError(
                f"Page order must list each of the {total} pages exactly once.")
        with pikepdf.Pdf.new() as part:
            for n in order:
                part.pages.append(doc.pages[n - 1])
            part.save(out)
    return out


# --------------------------------------------------------------------------
# annotations (written into the PDF so they travel with the file)
# --------------------------------------------------------------------------

@dataclass
class Annotation:
    """A markup annotation attached to a page of the document."""

    page: int                 # 1-based
    kind: str                # "highlight" | "underline" | "note"
    rect: tuple[float, float, float, float]   # x0, y0, x1, y1 in PDF points
    color: tuple[float, float, float] = (1.0, 0.85, 0.2)   # RGB 0..1
    text: str = ""           # note body / comment


def _rect_obj(rect):
    from pikepdf import Rectangle
    return Rectangle(rect[0], rect[1], rect[2], rect[3])


def add_annotations(path: str | os.PathLike, dest: str | os.PathLike,
                    annotations: list[Annotation],
                    password: str | None = None) -> Path:
    """Add markup annotations to pages.

    Highlights and underlines carry a quad-points array covering the marked
    text; notes are sticky text annotations.  Unlike Okular, the result is
    stored *inside* the PDF, so the marks survive being emailed or opened in
    another viewer.  Returns the output path.
    """
    pikepdf = _pikepdf()
    src, out = Path(path), Path(dest)
    with pikepdf.open(src, password=password or "") as doc:
        total = len(doc.pages)
        for ann in annotations:
            if not 1 <= ann.page <= total:
                raise PdfError(f"Page {ann.page} is outside this {total}-page doc.")
            page = doc.pages[ann.page - 1]
            obj = pikepdf.Dictionary(
                Type=pikepdf.Name("/Annot"),
                Subtype=pikepdf.Name(f"/{_subtype(ann.kind)}"),
                Rect=_rect_obj(ann.rect),
                Contents=pikepdf.String(ann.text or ""),
                C=_color_array(ann.color),
            )
            if ann.kind in ("highlight", "underline"):
                obj.QuadPoints = _quad_points(ann.rect)
            if ann.kind == "note":
                obj.Name = pikepdf.Name("/Comment")
                obj.Open = pikepdf.Name("/No")
            if "/Annots" not in page:
                page.Annots = pikepdf.Array()
            page.Annots.append(obj)
        doc.save(out)
    return out


def _subtype(kind: str) -> str:
    return {"highlight": "Highlight", "underline": "Underline",
            "note": "Text"}.get(kind, "Highlight")


def _color_array(color: tuple[float, float, float]):
    from pikepdf import Array
    return Array(list(color))


def _quad_points(rect) -> "Array":
    """QuadPoints covering the rectangle (4 corners, y flipped for PDF)."""
    from pikepdf import Array
    x0, y0, x1, y1 = rect
    # PDF quad points are 8 numbers: (x,y) of each corner, top row first.
    pts = [x0, y1, x1, y1, x0, y0, x1, y0]
    return Array(list(pts))


def list_annotations(path: str | os.PathLike,
                     password: str | None = None) -> list[Annotation]:
    """Read the annotations currently in the document (for the UI to show)."""
    pikepdf = _pikepdf()
    out: list[Annotation] = []
    with pikepdf.open(src := Path(path), password=password or "") as doc:
        for i, page in enumerate(doc.pages):
            fors = page.get("/Annots")
            if not fors:
                continue
            for ref in fors:
                ann = ref.get_object() if hasattr(ref, "get_object") else ref
                sub = str(ann.get("/Subtype", "")).lstrip("/")
                if sub not in ("Highlight", "Underline", "Text"):
                    continue
                rect = ann.get("/Rect")
                try:
                    r = (float(rect[0]), float(rect[1]),
                         float(rect[2]), float(rect[3]))
                except (TypeError, ValueError):
                    r = (0.0, 0.0, 0.0, 0.0)
                text = str(ann.get("/Contents", ""))
                color = (1.0, 0.85, 0.2)
                cobj = ann.get("/C")
                if cobj is not None:
                    try:
                        color = (float(cobj[0]), float(cobj[1]), float(cobj[2]))
                    except (TypeError, ValueError, IndexError):
                        pass
                out.append(Annotation(
                    page=i + 1,
                    kind={"Highlight": "highlight", "Underline": "underline",
                          "Text": "note"}.get(sub, "highlight"),
                    rect=r, color=color, text=text))
    return out


def unlock(path: str | os.PathLike, dest: str | os.PathLike,
           password: str) -> Path:
    """Write a decrypted copy.  Requires the correct password."""
    pikepdf = _pikepdf()
    src, out = Path(path), Path(dest)
    with pikepdf.open(src, password=password or "") as doc:
        doc.save(out)
    return out


# --------------------------------------------------------------------------
# security
# --------------------------------------------------------------------------

def protect(path: str | os.PathLike, dest: str | os.PathLike, *,
            user_password: str, owner_password: str | None = None,
            allow_printing: bool = True, allow_copying: bool = False,
            password: str | None = None) -> Path:
    """Encrypt with AES-256 (PDF 2.0 revision 6)."""
    pikepdf = _pikepdf()
    src, out = Path(path), Path(dest)
    if not user_password:
        raise PdfError("A password is required.")
    perms = pikepdf.Permissions(
        extract=allow_copying,
        print_lowres=allow_printing,
        print_highres=allow_printing,
        modify_annotation=False,
        modify_assembly=False,
        modify_form=False,
        modify_other=False,
    )
    with pikepdf.open(src, password=password or "") as doc:
        doc.save(out, encryption=pikepdf.Encryption(
            user=user_password, owner=owner_password or user_password,
            R=6, allow=perms))
    return out


def unlock(path: str | os.PathLike, dest: str | os.PathLike,
           password: str) -> Path:
    """Write a decrypted copy.  Requires the correct password."""
    pikepdf = _pikepdf()
    src, out = Path(path), Path(dest)
    try:
        with pikepdf.open(src, password=password) as doc:
            doc.save(out)
    except pikepdf.PasswordError as exc:
        raise PdfWrongPassword("Incorrect password.") from exc
    return out


def repair(path: str | os.PathLike, dest: str | os.PathLike,
           password: str | None = None) -> Path:
    """Rebuild a damaged PDF's cross-reference table via qpdf."""
    qpdf = _require("qpdf", "qpdf")
    src, out = Path(path), Path(dest)
    cmd = [qpdf, str(src), str(out)]
    if password:
        cmd.insert(1, f"--password={password}")
    res = run_tool(cmd, timeout=DEFAULT_TIMEOUT)
    # qpdf exit code 3 means "warnings, but output written".
    if res.returncode not in (0, 3) or not out.is_file():
        raise PdfError(f"Repair failed: {res.stderr.strip()[:300]}")
    return out


# --------------------------------------------------------------------------
# compression
# --------------------------------------------------------------------------

COMPRESSION_TIERS = {
    "screen": "/screen",        # 72 dpi, smallest
    "ebook": "/ebook",          # 150 dpi, good for reading
    "printer": "/printer",      # 300 dpi
    "prepress": "/prepress",    # 300 dpi, colour preserving
}


def compress(path: str | os.PathLike, dest: str | os.PathLike, *,
             tier: str = "ebook", password: str | None = None,
             ctx=None) -> tuple[Path, int, int]:
    """Re-encode via Ghostscript.  Returns ``(path, before, after)`` sizes."""
    if tier not in COMPRESSION_TIERS:
        raise PdfError(f"Unknown compression level: {tier}")
    gs = _require("gs", "ghostscript")
    src, out = Path(path), Path(dest)
    before = src.stat().st_size

    if ctx is not None:
        ctx.progress(-1, f"Compressing {src.name}…")
    cmd = [
        gs, "-q", "-dNOPAUSE", "-dBATCH", "-dSAFER",
        "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.7",
        f"-dPDFSETTINGS={COMPRESSION_TIERS[tier]}",
        "-dDetectDuplicateImages=true", "-dCompressFonts=true",
        f"-sOutputFile={out}",
    ]
    if password:
        cmd.append(f"-sPDFPassword={password}")
    cmd.append(str(src))

    res = run_tool(cmd, timeout=DEFAULT_TIMEOUT)
    if res.returncode != 0 or not out.is_file():
        raise PdfError(f"Compression failed: {res.stderr.strip()[:300]}")
    after = out.stat().st_size
    if ctx is not None:
        ctx.progress(100, f"{before // 1024} KB to {after // 1024} KB")
    return out, before, after


# --------------------------------------------------------------------------
# conversion
# --------------------------------------------------------------------------

def to_images(path: str | os.PathLike, dest_dir: str | os.PathLike, *,
              dpi: int = 150, fmt: str = "png", ranges: str | None = None,
              password: str | None = None, ctx=None) -> list[Path]:
    """Rasterise pages to individual image files."""
    fmt = fmt.lower().lstrip(".")
    if fmt not in ("png", "jpg", "jpeg", "tif", "tiff", "ppm"):
        raise PdfError(f"Cannot write pages as '{fmt}'.")
    out_dir = Path(dest_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    src = Path(path)
    written: list[Path] = []

    doc = open_doc(src, password)
    try:
        wanted = parse_ranges(ranges or "", doc.page_count)
        for i, n in enumerate(wanted):
            pix = doc[n - 1].get_pixmap(dpi=dpi)
            target = out_dir / f"{src.stem}-{n:03d}.{fmt}"
            if fmt in ("jpg", "jpeg"):
                pix.pil_save(target, format="JPEG", quality=92)
            else:
                pix.save(target)
            written.append(target)
            if ctx is not None:
                ctx.progress(int((i + 1) / len(wanted) * 100), f"Page {n}")
    finally:
        doc.close()
    return written


def from_images(sources: list[str | os.PathLike], dest: str | os.PathLike,
                *, ctx=None) -> Path:
    """Build a PDF from image files (delegates to the image backend)."""
    from .image import images_to_pdf
    return images_to_pdf(sources, dest, ctx=ctx)


def to_text_file(path: str | os.PathLike, dest: str | os.PathLike,
                 password: str | None = None) -> Path:
    out = Path(dest)
    out.write_text(extract_text(path, password=password), encoding="utf-8")
    return out


def from_office(path: str | os.PathLike, dest_dir: str | os.PathLike,
                *, ctx=None) -> Path:
    """Convert a document (docx/odt/xlsx/pptx) to PDF via LibreOffice."""
    soffice = _require("soffice", "libreoffice-fresh")
    src = Path(path)
    out_dir = Path(dest_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if ctx is not None:
        ctx.progress(-1, f"Converting {src.name}…")
    res = run_tool(
        [soffice, "--headless", "--convert-to", "pdf", "--outdir",
         str(out_dir), str(src)], timeout=DEFAULT_TIMEOUT)
    target = out_dir / (src.stem + ".pdf")
    if not target.is_file():
        raise PdfError(f"Conversion failed: {res.stderr.strip()[:300]}")
    return target


# --------------------------------------------------------------------------
# content operations (PyMuPDF)
# --------------------------------------------------------------------------

def watermark(path: str | os.PathLike, dest: str | os.PathLike, *,
              text: str, opacity: float = 0.15, size: int = 48,
              rotate: int = 45, password: str | None = None) -> Path:
    """Stamp diagonal text across every page."""
    fitz = _fitz()
    if not text:
        raise PdfError("Watermark text is empty.")
    doc = open_doc(path, password)
    try:
        for page in doc:
            rect = page.rect
            tw = fitz.TextWriter(rect, opacity=opacity)
            font = fitz.Font("helv")
            width = font.text_length(text, fontsize=size)
            point = fitz.Point(max(0, (rect.width - width) / 2),
                               rect.height / 2)
            tw.append(point, text, font=font, fontsize=size)
            tw.write_text(page, morph=(fitz.Point(rect.width / 2, rect.height / 2),
                                       fitz.Matrix(rotate)))
        doc.save(str(dest), garbage=3, deflate=True)
    finally:
        doc.close()
    return Path(dest)


def add_page_numbers(path: str | os.PathLike, dest: str | os.PathLike, *,
                     start: int = 1, size: int = 10,
                     password: str | None = None) -> Path:
    """Stamp a page number at the bottom centre of every page."""
    doc = open_doc(path, password)
    try:
        for i, page in enumerate(doc):
            label = str(start + i)
            page.insert_text((page.rect.width / 2 - len(label) * size * 0.28,
                              page.rect.height - size * 1.6),
                             label, fontsize=size, fontname="helv")
        doc.save(str(dest), garbage=3, deflate=True)
    finally:
        doc.close()
    return Path(dest)


def set_metadata(path: str | os.PathLike, dest: str | os.PathLike,
                 metadata: dict[str, str], password: str | None = None) -> Path:
    """Replace document metadata (title, author, subject, keywords)."""
    doc = open_doc(path, password)
    try:
        current = dict(doc.metadata or {})
        current.update({k: v for k, v in metadata.items() if v is not None})
        doc.set_metadata(current)
        doc.save(str(dest), garbage=3, deflate=True)
    finally:
        doc.close()
    return Path(dest)


def ocr(path: str | os.PathLike, dest: str | os.PathLike, *,
        language: str = "eng", force: bool = False, ctx=None) -> Path:
    """Add a searchable text layer using ocrmypdf."""
    tool = _require("ocrmypdf", "ocrmypdf")
    src, out = Path(path), Path(dest)
    cmd = [tool, "-l", language, "--output-type", "pdf"]
    cmd.append("--force-ocr" if force else "--skip-text")
    cmd += [str(src), str(out)]
    if ctx is not None:
        ctx.progress(-1, f"Running OCR on {src.name}…")
    res = run_tool(cmd, timeout=DEFAULT_TIMEOUT * 2)
    if res.returncode != 0 or not out.is_file():
        raise PdfError(f"OCR failed: {(res.stderr or res.stdout).strip()[:300]}")
    if ctx is not None:
        ctx.progress(100, "OCR complete")
    return out
