"""Running external tools safely.

Two rules apply to every subprocess CachyView spawns:

1. **Never a shell.**  Commands are argv lists, so filenames containing
   spaces, quotes or ``;`` cannot turn into shell injection.
2. **A clean environment.**  A ``PYTHONPATH`` inherited from an unrelated
   interpreter breaks any Python-based tool we call (ocrmypdf, img2pdf) with a
   confusing ImportError, because the child imports another ABI's compiled
   modules.  The variables that steer interpreter and library lookup are
   stripped from the child environment.

Every subprocess in the project should go through :func:`run` so both rules
hold everywhere, and long-running ones can be cancelled through *cancel*.
"""
from __future__ import annotations

import os
import subprocess
import time
from typing import Callable, Sequence

# Variables that redirect a child interpreter to foreign packages.
_STRIP = ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "PYTHONSTARTUP",
          "PYTHONNOUSERSITE", "PYTHONUSERBASE")


class ProcessCancelled(Exception):
    """Raised when a *cancel* callback asked a running tool to stop."""


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
        check: bool = False, text: bool = True,
        cancel: Callable[[], bool] | None = None) -> subprocess.CompletedProcess:
    """Run *cmd* (an argv list) with a sanitised environment.

    ``input_text`` is written to stdin (useful for tools that accept a prompt
    response there).  Set ``text=False`` for tools that emit binary data.  When
    ``cancel`` is given it is polled while the tool runs; returning ``True``
    kills the process and raises :class:`ProcessCancelled`.
    """
    if isinstance(cmd, str):        # guard against accidental shell usage
        raise TypeError("run() takes an argv list, not a shell string")
    if cancel is None:
        return subprocess.run(
            list(cmd),
            input=input_text if input_text is not None else ("" if text else b""),
            capture_output=True, text=text, timeout=timeout,
            env=clean_env(env_extra), check=check,
        )

    proc = subprocess.Popen(
        list(cmd), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=text, env=clean_env(env_extra))
    if input_text:
        try:
            assert proc.stdin is not None
            proc.stdin.write(input_text)
        except (BrokenPipeError, ValueError, OSError):
            pass
    try:
        if proc.stdin is not None:
            proc.stdin.close()
    except OSError:
        pass

    deadline = time.monotonic() + timeout
    while True:
        try:
            out, err = proc.communicate(timeout=0.25)
            break
        except subprocess.TimeoutExpired:
            if cancel():
                proc.kill()
                proc.communicate()
                raise ProcessCancelled() from None
            if time.monotonic() > deadline:
                proc.kill()
                proc.communicate()
                raise subprocess.TimeoutExpired(list(cmd), timeout) from None
    result = subprocess.CompletedProcess(list(cmd), proc.returncode, out, err)
    if check and proc.returncode:
        raise subprocess.CalledProcessError(proc.returncode, list(cmd), out, err)
    return result
