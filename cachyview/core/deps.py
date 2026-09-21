"""Runtime probing of optional external tools and Python modules.

A missing optional dependency must never crash the app: the feature is greyed
out and the UI can show the exact install command.
"""
from __future__ import annotations

import importlib.util
import shutil
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Dep:
    key: str
    kind: str          # "bin" or "py"
    probe: str         # executable name or module name
    package: str       # pacman/AUR package providing it
    purpose: str
    required: bool = False


DEPS: tuple[Dep, ...] = (
    Dep("pyqt6", "py", "PyQt6", "python-pyqt6", "GUI toolkit", required=True),
    Dep("pymupdf", "py", "pymupdf", "python-pymupdf", "PDF rendering and editing"),
    Dep("pikepdf", "py", "pikepdf", "python-pikepdf", "lossless PDF structure ops"),
    Dep("pillow", "py", "PIL", "python-pillow", "image loading and editing", required=True),
    Dep("pygments", "py", "pygments", "python-pygments", "syntax highlighting"),
    Dep("img2pdf", "py", "img2pdf", "img2pdf", "lossless image to PDF"),
    Dep("sevenzip", "bin", "7z", "7zip", "7z/zip/rar archive extraction", required=True),
    Dep("unrar", "bin", "unrar", "unrar", "RAR5 and encrypted RAR"),
    Dep("gs", "bin", "gs", "ghostscript", "PDF compression and PDF/A"),
    Dep("qpdf", "bin", "qpdf", "qpdf", "PDF repair, encrypt, linearize"),
    Dep("tesseract", "bin", "tesseract", "tesseract", "OCR engine"),
    Dep("ocrmypdf", "bin", "ocrmypdf", "ocrmypdf", "searchable PDF via OCR"),
    Dep("magick", "bin", "magick", "imagemagick", "exotic image formats and ops"),
    Dep("inkscape", "bin", "inkscape", "inkscape", "SVG conversion and export"),
    Dep("libreoffice", "bin", "soffice", "libreoffice-fresh", "office to PDF"),
    Dep("cwebp", "bin", "cwebp", "libwebp", "WebP encoding"),
    Dep("oxipng", "bin", "oxipng", "oxipng", "lossless PNG optimisation"),
    Dep("jpegoptim", "bin", "jpegoptim", "jpegoptim", "lossless JPEG optimisation"),
    Dep("pillow_heif", "py", "pillow_heif", "python-pillow-heif", "HEIC/HEIF decoding"),
    Dep("pillow_avif", "py", "pillow_avif", "python-pillow-avif", "AVIF decoding"),
    Dep("pillow_jxl", "py", "pillow_jxl", "python-pillow-jxl", "JPEG XL decoding"),
    Dep("rawpy", "py", "rawpy", "python-rawpy", "camera RAW decoding"),
    Dep("lz4", "py", "lz4", "python-lz4", "LZ4 archive streams"),
    Dep("yaml", "py", "yaml", "python-yaml", "YAML formatting and validation"),
)

BY_KEY = {d.key: d for d in DEPS}


@lru_cache(maxsize=None)
def have(key: str) -> bool:
    dep = BY_KEY.get(key)
    if dep is None:
        return False
    if dep.kind == "bin":
        return shutil.which(dep.probe) is not None
    # PyMuPDF is importable as `pymupdf` on recent versions and only as the
    # legacy `fitz` shim on older ones; accept either.
    probes = (dep.probe, "fitz") if dep.probe == "pymupdf" else (dep.probe,)
    for probe in probes:
        try:
            if importlib.util.find_spec(probe) is None:
                continue
            # A module can be present but fail to import (e.g. PyMuPDF's native
            # libmupdf was removed by a partial upgrade).  Treat that as missing.
            importlib.import_module(probe)
        except (ImportError, ValueError, OSError):
            continue
        return True
    return False


def missing(required_only: bool = False) -> list[Dep]:
    return [d for d in DEPS if (d.required or not required_only) and not have(d.key)]


def install_hint(keys: list[str] | tuple[str, ...]) -> str:
    pkgs = sorted({BY_KEY[k].package for k in keys if k in BY_KEY and not have(k)})
    return f"paru -S --needed {' '.join(pkgs)}" if pkgs else ""


def report() -> str:
    lines = []
    for d in DEPS:
        mark = "ok " if have(d.key) else ("MISSING (required)" if d.required else "-  ")
        lines.append(f"{mark:20} {d.key:12} {d.package:22} {d.purpose}")
    return "\n".join(lines)
