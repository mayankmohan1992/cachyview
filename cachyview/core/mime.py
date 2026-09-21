"""MIME detection and routing to document kinds. Pure stdlib, no Qt."""
from __future__ import annotations

import mimetypes
import os
import subprocess
from enum import Enum
from pathlib import Path

from .process import run as run_tool


class Kind(str, Enum):
    ARCHIVE = "archive"
    PDF = "pdf"
    IMAGE = "image"
    SVG = "svg"
    TEXT = "text"
    BINARY = "binary"


ARCHIVE_EXTS = {
    ".zip", ".7z", ".rar", ".tar", ".gz", ".tgz", ".bz2", ".tbz2", ".xz", ".txz",
    ".zst", ".tzst", ".lz4", ".lzma", ".iso", ".cab", ".ar", ".cpio", ".deb",
    ".rpm", ".jar", ".apk", ".xpi", ".epub", ".cbz", ".cbr", ".cb7", ".arj", ".lzh",
}
PDF_EXTS = {".pdf"}
SVG_EXTS = {".svg", ".svgz"}
IMAGE_EXTS = {
    ".png", ".jpg", ".jpeg", ".jpe", ".gif", ".bmp", ".webp", ".tif", ".tiff",
    ".ico", ".ppm", ".pgm", ".pbm", ".pnm", ".xpm", ".tga",
    ".avif", ".jxl", ".heic", ".heif", ".psd", ".dds", ".jp2", ".j2k",
    ".cr2", ".cr3", ".nef", ".arw", ".dng", ".orf", ".rw2", ".raf", ".pef",
}
# Extensions that are textual even though libmagic may disagree.
TEXT_EXTS = {
    ".txt", ".md", ".markdown", ".rst", ".log", ".csv", ".tsv", ".json", ".yaml",
    ".yml", ".toml", ".ini", ".cfg", ".conf", ".xml", ".html", ".htm", ".css",
    ".js", ".ts", ".jsx", ".tsx", ".py", ".pyi", ".sh", ".bash", ".zsh", ".fish",
    ".c", ".h", ".cpp", ".hpp", ".cc", ".rs", ".go", ".java", ".kt", ".rb", ".pl",
    ".php", ".lua", ".sql", ".diff", ".patch", ".desktop", ".service", ".env",
    ".gitignore", ".editorconfig", ".pkgbuild", ".nix", ".vim", ".el", ".tex",
}

# Archives whose "extension" is ambiguous: .gz/.xz/.bz2 wrapping a tar.
_TAR_DOUBLE = {".tar.gz", ".tar.bz2", ".tar.xz", ".tar.zst", ".tar.lz4", ".tar.lzma"}

_MAGIC = [
    (b"%PDF-", Kind.PDF),
    (b"\x89PNG\r\n\x1a\n", Kind.IMAGE),
    (b"\xff\xd8\xff", Kind.IMAGE),
    (b"GIF87a", Kind.IMAGE),
    (b"GIF89a", Kind.IMAGE),
    (b"BM", Kind.IMAGE),
    (b"PK\x03\x04", Kind.ARCHIVE),
    (b"PK\x05\x06", Kind.ARCHIVE),
    (b"7z\xbc\xaf\x27\x1c", Kind.ARCHIVE),
    (b"Rar!\x1a\x07", Kind.ARCHIVE),
    (b"\x1f\x8b", Kind.ARCHIVE),
    (b"BZh", Kind.ARCHIVE),
    (b"\xfd7zXZ\x00", Kind.ARCHIVE),
    (b"(\xb5/\xfd", Kind.ARCHIVE),
    (b"\x04\x22\x4d\x18", Kind.ARCHIVE),
    (b"!<arch>", Kind.ARCHIVE),
    (b"MSCF", Kind.ARCHIVE),
]


def _magic_kind(head: bytes) -> Kind | None:
    for sig, kind in _MAGIC:
        if head.startswith(sig):
            return kind
    # RIFF....WEBP
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return Kind.IMAGE
    # ISO-BMFF: ....ftyp{avif,heic,heif,mif1}
    if head[4:8] == b"ftyp" and head[8:12] in (b"avif", b"heic", b"heif", b"mif1", b"avis"):
        return Kind.IMAGE
    # TIFF
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return Kind.IMAGE
    # JPEG XL
    if head.startswith(b"\xff\x0a") or head[:12] == b"\x00\x00\x00\x0cJXL \r\n\x87\n":
        return Kind.IMAGE
    # ISO 9660 has its magic at offset 32769, handled by the caller if needed.
    return None


def looks_textual(head: bytes) -> bool:
    """Heuristic: no NUL bytes and mostly printable/UTF-8 decodable."""
    if not head:
        return True
    if b"\x00" in head:
        return False
    try:
        head.decode("utf-8")
        return True
    except UnicodeDecodeError:
        pass
    printable = sum(1 for b in head if 32 <= b < 127 or b in (9, 10, 13))
    return printable / len(head) > 0.85


def detect_kind(path: str | os.PathLike) -> Kind:
    """Classify a file. Magic bytes win; extension is the tie-breaker."""
    p = Path(path)
    name = p.name.lower()
    suffix = p.suffix.lower()

    head = b""
    try:
        with open(p, "rb") as fh:
            head = fh.read(4096)
    except OSError:
        pass

    if suffix == ".svg" or name.endswith(".svgz"):
        return Kind.SVG

    magic = _magic_kind(head)
    if magic is not None:
        # A zip container may really be an epub/cbz/odt — still an archive for us.
        return magic

    if any(name.endswith(d) for d in _TAR_DOUBLE) or suffix in ARCHIVE_EXTS:
        return Kind.ARCHIVE
    if suffix in PDF_EXTS:
        return Kind.PDF
    if suffix in IMAGE_EXTS:
        return Kind.IMAGE
    if suffix in TEXT_EXTS or name in TEXT_EXTS:
        return Kind.TEXT

    if looks_textual(head):
        return Kind.TEXT
    return Kind.BINARY


def mime_type(path: str | os.PathLike) -> str:
    guessed, _ = mimetypes.guess_type(str(path))
    if guessed:
        return guessed
    try:
        out = run_tool(
            ["file", "--brief", "--mime-type", "--", str(path)],
            timeout=5)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return "application/octet-stream"
