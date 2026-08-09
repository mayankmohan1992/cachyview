"""Running external tools safely.

Two rules apply to every subprocess CachyView spawns:

1. **Never a shell.**  Commands are argv lists, so filenames containing
   spaces, quotes or ``;`` cannot turn into shell injection.
2. **A clean environment.**  A ``PYTHONPATH`` inherited from an unrelated
   interpreter breaks any Python-based tool we call (ocrmypdf, img2pdf) with a
   confusing ImportError, because the child imports another ABI's compiled
   modules.  The variables that steer interpreter and library lookup are
   stripped from the child environment.
"""
from __future__ import annotations

import os
import subprocess
from typing import Sequence

# Variables that redirect a child interpreter to foreign packages.
_STRIP = ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "PYTHONSTARTUP",
          "PYTHONNOUSERSITE", "PYTHONUSERBASE")


def clean_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """A copy of os.environ without interpreter-redirecting variables."""
    env = {k: v for k, v in os.environ.items() if k not in _STRIP}
    # A venv also leaves its bin dir first on PATH; drop those entries so the
    # child resolves system tools rather than venv shims.
    venv = os.environ.get("VIRTUAL_ENV")
    if venv:
        parts = [p for p in env.get("PATH", "").split(os.pathsep)
                 if p and not p.startswith(venv)]
        if parts:
            env["PATH"] = os.pathsep.join(parts)
    if extra:
        env.update(extra)
    return env


def run(cmd: Sequence[str], *, input_text: str | None = None,
        timeout: int = 300, env_extra: dict[str, str] | None = None,
        check: bool = False) -> subprocess.CompletedProcess:
    """Run *cmd* (an argv list) with a sanitised environment.

    ``input_text`` is written to stdin, which is how passwords reach archive
    tools without ever appearing in the process table.
    """
    if isinstance(cmd, str):        # guard against accidental shell usage
        raise TypeError("run() takes an argv list, not a shell string")
    return subprocess.run(
        list(cmd),
        input=input_text if input_text is not None else "",
        capture_output=True, text=True, timeout=timeout,
        env=clean_env(env_extra), check=check,
    )
