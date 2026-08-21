"""CachyView — archive, PDF, image and text toolkit for CachyOS.

Guards against a foreign PYTHONPATH shadowing our dependencies. Some launchers
(IDE terminals, other apps' venvs) export a PYTHONPATH pointing at an unrelated
interpreter's site-packages; importing a compiled module such as Pillow from
there against a different Python ABI fails with a confusing ImportError. We
drop any site-packages entry that does not belong to the running interpreter
before the first third-party import.
"""
from __future__ import annotations

import sys
import sysconfig

__version__ = "0.2.0"


def _purge_foreign_site_packages() -> list[str]:
    """Remove sys.path entries from another interpreter's site-packages."""
    ours = {sysconfig.get_path("purelib"), sysconfig.get_path("platlib")}
    tag = f"python{sys.version_info.major}.{sys.version_info.minor}"
    removed = []
    for entry in list(sys.path):
        if not entry or entry in ours:
            continue
        norm = entry.replace("\\", "/")
        if "site-packages" in norm and f"/{tag}/" not in norm:
            sys.path.remove(entry)
            removed.append(entry)
    return removed


PURGED_PATHS = _purge_foreign_site_packages()
