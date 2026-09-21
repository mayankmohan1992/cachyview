"""MIME detection tests using real magic bytes."""
import pytest

from cachyview.core.mime import Kind, detect_kind, looks_textual

SAMPLES = {
    "a.pdf": b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj",
    "a.png": b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR",
    "a.jpg": b"\xff\xd8\xff\xe0\x00\x10JFIF\x00",
    "a.gif": b"GIF89a\x01\x00\x01\x00",
    "a.zip": b"PK\x03\x04\x14\x00\x00\x00\x08\x00",
    "a.7z": b"7z\xbc\xaf\x27\x1c\x00\x04",
    "a.rar": b"Rar!\x1a\x07\x01\x00",
    "a.gz": b"\x1f\x8b\x08\x00\x00\x00\x00\x00",
    "a.xz": b"\xfd7zXZ\x00\x00\x04",
    "a.zst": b"(\xb5/\xfd\x00\x58",
    "a.webp": b"RIFF\x24\x00\x00\x00WEBPVP8 ",
    "a.tif": b"II*\x00\x08\x00\x00\x00",
    "a.bmp": b"BM\x36\x00\x00\x00",
}

EXPECTED = {
    "a.pdf": Kind.PDF, "a.png": Kind.IMAGE, "a.jpg": Kind.IMAGE,
    "a.gif": Kind.IMAGE, "a.zip": Kind.ARCHIVE, "a.7z": Kind.ARCHIVE,
    "a.rar": Kind.ARCHIVE, "a.gz": Kind.ARCHIVE, "a.xz": Kind.ARCHIVE,
    "a.zst": Kind.ARCHIVE, "a.webp": Kind.IMAGE, "a.tif": Kind.IMAGE,
    "a.bmp": Kind.IMAGE,
}


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_magic_detection(tmp_path, name):
    f = tmp_path / name
    f.write_bytes(SAMPLES[name])
    assert detect_kind(f) == EXPECTED[name]


def test_magic_beats_wrong_extension(tmp_path):
    """A PDF named .txt is still a PDF."""
    f = tmp_path / "lying.txt"
    f.write_bytes(SAMPLES["a.pdf"])
    assert detect_kind(f) == Kind.PDF


@pytest.mark.parametrize("name,content", [
    ("notes.md", b"# Hello\n\nSome text."),
    ("data.json", b'{"a": 1}'),
    ("script.py", b"import os\n"),
    ("no_ext_but_text", b"plain ascii content here\n"),
])
def test_text_detection(tmp_path, name, content):
    f = tmp_path / name
    f.write_bytes(content)
    assert detect_kind(f) == Kind.TEXT


def test_binary_fallback(tmp_path):
    f = tmp_path / "blob.dat"
    f.write_bytes(bytes(range(256)) * 4)
    assert detect_kind(f) == Kind.BINARY


def test_svg_is_svg(tmp_path):
    f = tmp_path / "vec.svg"
    f.write_bytes(b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"/>')
    assert detect_kind(f) == Kind.SVG


def test_empty_file_is_text(tmp_path):
    f = tmp_path / "empty"
    f.write_bytes(b"")
    assert detect_kind(f) == Kind.TEXT


def test_looks_textual():
    assert looks_textual(b"hello world")
    assert looks_textual("caf\u00e9 na\u00efve".encode())
    assert not looks_textual(b"\x00\x01\x02")
