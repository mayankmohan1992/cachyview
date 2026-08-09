"""Subprocess environment sanitising.

Regression guard: a foreign PYTHONPATH inherited by a child process breaks
every python-based tool CachyView shells out to (ocrmypdf, img2pdf) with an
ImportError about a compiled module built for a different ABI.
"""
import os
import shutil
import sys

import pytest

from cachyview.core.process import clean_env, run

FOREIGN = "/some/other/lib/python2.7/site-packages"


def test_clean_env_strips_pythonpath(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", FOREIGN)
    assert "PYTHONPATH" not in clean_env()


@pytest.mark.parametrize("var", [
    "PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "PYTHONSTARTUP",
])
def test_clean_env_strips_all_interpreter_vars(monkeypatch, var):
    monkeypatch.setenv(var, "/somewhere")
    assert var not in clean_env()


def test_clean_env_keeps_normal_vars(monkeypatch):
    monkeypatch.setenv("HOME", "/home/tester")
    monkeypatch.setenv("LANG", "en_GB.UTF-8")
    env = clean_env()
    assert env["HOME"] == "/home/tester"
    assert env["LANG"] == "en_GB.UTF-8"


def test_clean_env_drops_venv_from_path(monkeypatch):
    monkeypatch.setenv("VIRTUAL_ENV", "/tmp/myvenv")
    monkeypatch.setenv("PATH", "/tmp/myvenv/bin:/usr/bin:/bin")
    assert clean_env()["PATH"] == "/usr/bin:/bin"


def test_clean_env_extra_overrides(monkeypatch):
    assert clean_env({"MY_FLAG": "1"})["MY_FLAG"] == "1"


def test_child_does_not_see_pythonpath(monkeypatch):
    """The whole point: the child must not inherit the poisoned path."""
    monkeypatch.setenv("PYTHONPATH", FOREIGN)
    res = run([sys.executable, "-c",
               "import os; print(os.environ.get('PYTHONPATH', 'UNSET'))"])
    assert res.stdout.strip() == "UNSET"


def test_child_imports_work_under_foreign_pythonpath(tmp_path, monkeypatch):
    """A decoy module on PYTHONPATH must not reach the child."""
    decoy = tmp_path / "lib" / "python2.7" / "site-packages"
    (decoy / "PIL").mkdir(parents=True)
    (decoy / "PIL" / "__init__.py").write_text("raise ImportError('decoy')")
    monkeypatch.setenv("PYTHONPATH", str(decoy))

    res = run([sys.executable, "-c", "from PIL import Image; print('PIL OK')"])
    assert res.returncode == 0, res.stderr
    assert "PIL OK" in res.stdout


@pytest.mark.skipif(not shutil.which("ocrmypdf"), reason="needs ocrmypdf")
def test_ocrmypdf_survives_foreign_pythonpath(monkeypatch):
    """The exact failure that motivated this module."""
    monkeypatch.setenv("PYTHONPATH",
                       "/home/mm/.hermes/hermes-agent/venv/lib/python3.11/site-packages")
    res = run(["ocrmypdf", "--version"], timeout=60)
    assert res.returncode == 0, res.stderr
    # ocrmypdf prints its version on stderr, not stdout.
    version = (res.stdout + res.stderr).strip()
    assert version and version[0].isdigit(), version


def test_run_rejects_shell_string():
    """Guard against accidentally passing a shell command."""
    with pytest.raises(TypeError):
        run("echo hello")           # type: ignore[arg-type]


def test_run_passes_stdin():
    res = run([sys.executable, "-c",
               "import sys; print(sys.stdin.read().strip().upper())"],
              input_text="quiet\n")
    assert "QUIET" in res.stdout


def test_run_captures_exit_code():
    assert run([sys.executable, "-c", "raise SystemExit(3)"]).returncode == 3


def test_run_no_shell_injection(tmp_path):
    """A filename containing shell metacharacters must stay literal."""
    marker = tmp_path / "canary"
    nasty = f"x; touch {marker}"
    res = run([sys.executable, "-c", "import sys; print(sys.argv[1])", nasty])
    assert nasty in res.stdout
    assert not marker.exists()
