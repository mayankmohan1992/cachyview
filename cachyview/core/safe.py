"""Atomic file replacement.

Overwriting a user's document in place is dangerous: if the write is
interrupted (crash, power loss, disk full) the original is gone.  Every
destructive save in CachyView goes through :func:`replace_in_place`, which
writes to a sibling temp file and only moves it over the target once the
write has fully succeeded.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path


def replace_in_place(target: str | os.PathLike, write: Callable[[Path], None]) -> Path:
    """Atomically replace *target* with the file produced by *write*.

    ``write`` receives a temporary ``Path`` and must write the final bytes to
    it.  On success the temp file is moved over *target* (and the original is
    moved to ``target~`` first, so it can be recovered).  On any failure the
    temp file is removed and *target* is untouched.

    Returns the path that now holds the data (== *target*).
    """
    target = Path(target)
    if not target.exists():
        # Nothing to back up; just write straight there.  Use a sibling temp
        # and rename into place so a half-written file never appears as the
        # final name, then return early (no backup / no self-replace).
        tmp = target.with_name(f".{target.name}.cachyview-tmp-{os.getpid()}")
        try:
            write(tmp)
            if not tmp.exists() or tmp.stat().st_size == 0:
                raise OSError("write produced no data")
            os.replace(tmp, target)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        return target

    tmp = target.with_name(f".{target.name}.cachyview-tmp-{os.getpid()}")
    try:
        write(tmp)
        if not tmp.exists() or tmp.stat().st_size == 0:
            raise OSError("write produced no data")
        backup = target.with_name(f"{target.name}~")
        # Never let a stale backup clobber a real one.
        backup.unlink(missing_ok=True)
        os.replace(target, backup)
        os.replace(tmp, target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return target


def safe_backup_path(target: str | os.PathLike) -> Path:
    """The ``target~`` recovery path that :func:`replace_in_place` leaves."""
    target = Path(target)
    return target.with_name(f"{target.name}~")


def write_text_atomic(path: str | os.PathLike, text: str, *,
                      encoding: str = "utf-8") -> Path:
    """Write *text* via a sibling temp file + rename, so a crash cannot
    truncate an existing configuration file."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.cachyview-tmp-{os.getpid()}")
    try:
        with open(tmp, "w", encoding=encoding) as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return target
