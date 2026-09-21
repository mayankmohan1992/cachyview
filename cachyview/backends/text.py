"""Text file backend: encoding detection, safe loading of large files. No Qt."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

# Files bigger than this are loaded head-only unless the caller forces full read.
LARGE_FILE_BYTES = 8 * 1024 * 1024

_ENCODINGS = ("utf-8", "utf-8-sig", "utf-16", "latin-1")


@dataclass
class TextDoc:
    path: Path
    text: str
    encoding: str
    newline: str          # "\n", "\r\n" or "\r"
    truncated: bool
    size: int


def detect_newline(sample: str) -> str:
    if "\r\n" in sample:
        return "\r\n"
    if "\r" in sample and "\n" not in sample:
        return "\r"
    return "\n"


def load(path: str | os.PathLike, max_bytes: int = LARGE_FILE_BYTES) -> TextDoc:
    p = Path(path)
    size = p.stat().st_size
    raw = p.read_bytes() if size <= max_bytes else p.open("rb").read(max_bytes)
    truncated = size > max_bytes

    text = None
    used = "utf-8"
    for enc in _ENCODINGS:
        try:
            text = raw.decode(enc)
            used = enc
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = raw.decode("utf-8", errors="replace")
        used = "utf-8 (replaced)"

    nl = detect_newline(text[:65536])
    return TextDoc(path=p, text=text.replace("\r\n", "\n").replace("\r", "\n"),
                   encoding=used, newline=nl, truncated=truncated, size=size)


def save(doc: TextDoc, text: str, *, encoding: str | None = None,
         newline: str | None = None) -> None:
    """Atomic write: temp file in the same dir, then os.replace."""
    enc = (encoding or doc.encoding).replace(" (replaced)", "")
    nl = newline or doc.newline
    data = text.replace("\n", nl).encode(enc, errors="replace")
    tmp = doc.path.with_name(doc.path.name + ".cachyview.tmp")
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.chmod(tmp, doc.path.stat().st_mode & 0o7777)
        except OSError:
            pass
        os.replace(tmp, doc.path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def pretty_print(text: str, fmt: str) -> str:
    """Reformat JSON/XML. Raises ValueError with a useful message on bad input."""
    if fmt == "json":
        try:
            return json.dumps(json.loads(text), indent=2, ensure_ascii=False)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON at line {exc.lineno}, col {exc.colno}: {exc.msg}") from exc
    if fmt == "xml":
        import xml.dom.minidom as minidom
        from xml.parsers.expat import ExpatError
        try:
            return minidom.parseString(text).toprettyxml(indent="  ")
        except ExpatError as exc:
            raise ValueError(f"Invalid XML: {exc}") from exc
    if fmt == "yaml":
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise ValueError("Formatting YAML needs PyYAML installed") from exc
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ValueError(f"Invalid YAML: {exc}") from exc
        return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    raise ValueError(f"Unsupported format: {fmt}")


def minify(text: str, fmt: str) -> str:
    if fmt == "json":
        try:
            return json.dumps(json.loads(text), separators=(",", ":"),
                              ensure_ascii=False)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON: {exc.msg}") from exc
    if fmt == "xml":
        import re
        return re.sub(r">\s+<", "><", pretty_print(text, "xml"))
    raise ValueError(f"Unsupported format: {fmt}")


def validate(text: str, fmt: str) -> str:
    """Return '' if valid, otherwise a one-line error."""
    try:
        if fmt == "json":
            json.loads(text)
        elif fmt == "xml":
            import xml.etree.ElementTree as ET
            ET.fromstring(text)
        elif fmt == "toml":
            import tomllib
            tomllib.loads(text)
        elif fmt == "yaml":
            try:
                import yaml  # type: ignore
            except ImportError as exc:
                raise ValueError("PyYAML is not installed") from exc
            yaml.safe_load(text)
        else:
            raise ValueError(f"Unsupported format: {fmt}")
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(str(exc)) from exc
    return ""


def csv_rows(text: str, *, max_rows: int = 5000) -> tuple[list[str], list[list[str]]]:
    import csv
    import io
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    rows = []
    header: list[str] = []
    for i, row in enumerate(reader):
        if i == 0:
            header = row
            continue
        rows.append(row)
        if len(rows) >= max_rows:
            break
    return header, rows


def unified_diff(a: str, b: str, name_a: str = "a", name_b: str = "b") -> str:
    import difflib
    return "".join(difflib.unified_diff(
        a.splitlines(keepends=True), b.splitlines(keepends=True),
        fromfile=name_a, tofile=name_b))


def hex_dump(data: bytes, width: int = 16, offset: int = 0) -> str:
    lines = []
    for i in range(0, len(data), width):
        chunk = data[i:i + width]
        hexs = " ".join(f"{b:02x}" for b in chunk).ljust(width * 3 - 1)
        ascii_ = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{offset + i:08x}  {hexs}  |{ascii_}|")
    return "\n".join(lines)
