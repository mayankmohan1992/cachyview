"""Local UI preferences. No network."""
from __future__ import annotations

import json
import os
from pathlib import Path

from .safe import write_text_atomic


def _path() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) / "cachyview" if xdg else Path.home() / ".config" / "cachyview"
    base.mkdir(parents=True, exist_ok=True)
    return base / "settings.json"


DEFAULTS = {
    "restore_session": True,
    "become_default": False,
}


def load() -> dict:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return dict(DEFAULTS)
    out = dict(DEFAULTS)
    out.update({k: data[k] for k in DEFAULTS if k in data})
    return out


def save(state: dict) -> None:
    current = load()
    current.update(state)
    write_text_atomic(_path(), json.dumps(current, indent=2))
