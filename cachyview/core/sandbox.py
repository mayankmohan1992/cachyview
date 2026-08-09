"""Per-session scratch space with hard security guarantees.

All extraction/render temp files live under a 0700 dir in $XDG_RUNTIME_DIR
(tmpfs, wiped on logout) and are purged when the app exits.
"""
from __future__ import annotations

import atexit
import os
import shutil
import tempfile
import weakref
from pathlib import Path


class UnsafePath(Exception):
    """An archive member tried to escape the extraction root."""


def runtime_root() -> Path:
    base = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    root = Path(base) / "cachyview"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(root, 0o700)
    except OSError:
        pass
    return root


class Sandbox:
    """A disposable 0700 directory. Use as a context manager or rely on atexit."""

    _live: "weakref.WeakSet[Sandbox]" = weakref.WeakSet()

    def __init__(self, prefix: str = "s-"):
        self.path = Path(tempfile.mkdtemp(prefix=prefix, dir=runtime_root()))
        os.chmod(self.path, 0o700)
        Sandbox._live.add(self)

    def __enter__(self) -> "Sandbox":
        return self

    def __exit__(self, *exc: object) -> None:
        self.cleanup()

    def cleanup(self) -> None:
        shutil.rmtree(self.path, ignore_errors=True)

    def resolve_member(self, member: str) -> Path:
        """Map an archive member name to a safe path inside this sandbox.

        Rejects absolute paths, drive letters, '..' traversal, and any result
        that resolves outside the sandbox root (covers symlink-escape too).
        """
        return safe_join(self.path, member)


def safe_join(root: Path, member: str) -> Path:
    if not member or member in (".", "/"):
        raise UnsafePath(f"invalid member name: {member!r}")
    name = member.replace("\\", "/")
    if name.startswith("/") or (len(name) > 1 and name[1] == ":"):
        raise UnsafePath(f"absolute path in archive: {member!r}")
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise UnsafePath(f"path traversal in archive: {member!r}")
    root_r = root.resolve()
    target = (root_r / Path(*parts)).resolve()
    if target != root_r and root_r not in target.parents:
        raise UnsafePath(f"escapes extraction root: {member!r}")
    return target


@atexit.register
def _purge_all() -> None:
    for sb in list(Sandbox._live):
        sb.cleanup()
