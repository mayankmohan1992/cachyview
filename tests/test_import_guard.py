"""The package must import cleanly even with a foreign PYTHONPATH exported."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(code: str, env_extra: dict) -> subprocess.CompletedProcess:
    import os
    env = dict(os.environ, **env_extra)
    return subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env,
                          capture_output=True, text=True)


def test_purges_foreign_site_packages():
    """A site-packages dir from another Python version must be dropped."""
    code = (
        "import cachyview, sys;"
        "print('PURGED', len(cachyview.PURGED_PATHS));"
        "print('LEFT', [p for p in sys.path if 'python2.7' in p])"
    )
    r = _run(code, {"PYTHONPATH": "/nonexistent/lib/python2.7/site-packages"})
    assert r.returncode == 0, r.stderr
    assert "PURGED 1" in r.stdout, r.stdout
    assert "LEFT []" in r.stdout, r.stdout


def test_keeps_our_own_paths():
    """Our own interpreter's site-packages must survive the purge."""
    code = (
        "import cachyview, sysconfig, sys;"
        "print('OK', sysconfig.get_path('purelib') in sys.path"
        " or sysconfig.get_path('platlib') in sys.path)"
    )
    r = _run(code, {})
    assert r.returncode == 0, r.stderr
    assert "OK True" in r.stdout, r.stdout


def test_deps_import_under_foreign_pythonpath():
    """The real failure mode: Pillow shadowed by another ABI's build."""
    foreign = "/home/mm/.hermes/hermes-agent/venv/lib/python3.11/site-packages"
    if not Path(foreign).is_dir() or f"python3.{sys.version_info.minor}" in foreign:
        import pytest
        pytest.skip("no foreign site-packages available to test against")
    code = "import cachyview; from PIL import Image; print('PIL OK', Image.__name__)"
    r = _run(code, {"PYTHONPATH": foreign})
    assert r.returncode == 0, f"stdout={r.stdout} stderr={r.stderr}"
    assert "PIL OK" in r.stdout
