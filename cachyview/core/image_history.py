"""Persistent image edit history.

Each edited source image keeps its ordered list of :class:`Op` edits in a small
JSON store.  When the same image is reopened the stack is replayed so the user
picks up exactly where they left off.  History is per original file path; saving
a copy does not alter the stored stack (the source stays the source).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..backends.image import Op


def _store_path() -> Path:
    base = Path(
        __import__("os").environ.get(
            "XDG_CONFIG_HOME",
            Path.home() / ".config"))
    p = base / "cachyview" / "image_history.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load() -> dict[str, list[dict]]:
    p = _store_path()
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text() or "{}")
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict[str, list[dict]]) -> None:
    _store_path().write_text(json.dumps(data, indent=2))


def remember(source: str | Path, ops: list[Op]) -> None:
    """Persist the current edit stack for *source*."""
    data = _load()
    key = str(Path(source).expanduser().resolve())
    data[key] = [{"name": o.name, "args": o.args} for o in ops]
    if not data[key]:
        data.pop(key, None)
    _save(data)


def load(source: str | Path) -> list[Op]:
    """Return the stored edit stack for *source* (empty list if none)."""
    key = str(Path(source).expanduser().resolve())
    return [Op(name=d["name"], args=d.get("args", {}))
            for d in _load().get(key, [])]


def clear(source: str | Path) -> None:
    data = _load()
    key = str(Path(source).expanduser().resolve())
    if key in data:
        del data[key]
        _save(data)
