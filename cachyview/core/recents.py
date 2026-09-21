"""Persistent recents and pinned files.

Stored in ``$XDG_CONFIG_HOME/cachyview/recents.json`` so the list survives
restarts.  Recents are capped (most-recent first); pins are kept indefinitely
until the user removes them.  No network, no telemetry — just a local file.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .safe import write_text_atomic

MAX_RECENTS = 25


def _store_dir() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) / "cachyview" if xdg else Path.home() / ".config" / "cachyview"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _recents_path() -> Path:
    return _store_dir() / "recents.json"


def load() -> dict:
    """Return ``{"recents": [...], "pins": [...]}`` (paths as strings)."""
    try:
        data = json.loads(_recents_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"recents": [], "pins": []}
    return {"recents": list(data.get("recents", [])),
            "pins": list(data.get("pins", [])),
            "session": list(data.get("session", []))}


def save(state: dict) -> None:
    write_text_atomic(_recents_path(), json.dumps(state, indent=2))


def remember(path: str | Path) -> dict:
    """Add *path* to the front of recents, drop duplicates, cap the list."""
    p = str(Path(path).expanduser())
    state = load()
    recents = [r for r in state["recents"] if r != p]
    recents.insert(0, p)
    state["recents"] = recents[:MAX_RECENTS]
    save(state)
    return state


def pin(path: str | Path) -> dict:
    p = str(Path(path).expanduser())
    state = load()
    if p not in state["pins"]:
        state["pins"].append(p)
        save(state)
    return state


def unpin(path: str | Path) -> dict:
    p = str(Path(path).expanduser())
    state = load()
    state["pins"] = [x for x in state["pins"] if x != p]
    save(state)
    return state


def existing(state: dict) -> dict:
    """Filter to files that still exist on disk (best-effort, no errors)."""
    def keep(p: str) -> bool:
        try:
            return Path(p).is_file()
        except OSError:
            return False
    return {"recents": [p for p in state["recents"] if keep(p)],
            "pins": [p for p in state["pins"] if keep(p)]}
