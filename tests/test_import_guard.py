"""The package must import cleanly even with a foreign PYTHONPATH exported."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OTHER = f"python3.{sys.version_info.minor - 1}"   # a version that isn't ours


def run(code: str, pythonpath: str | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    if pythonpath:
        env["PYTHONPATH"] = pythonpath
    return subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env,
                          capture_output=True, text=True)


def test_purges_foreign_site_packages():
    r = run("import cachyview, sys;"
            "print('PURGED', len(cachyview.PURGED_PATHS));"
            f"print('LEFT', [p for p in sys.path if '{OTHER}' in p])",
            f"/nonexistent/lib/{OTHER}/site-packages")
    assert r.returncode == 0, r.stderr
    assert "PURGED 1" in r.stdout and "LEFT []" in r.stdout, r.stdout


def test_keeps_our_own_paths():
    r = run("import cachyview, sysconfig, sys;"
            "print('OK', {sysconfig.get_path('purelib'),"
            " sysconfig.get_path('platlib')} & set(sys.path) != set())")
    assert r.returncode == 0, r.stderr
    assert "OK True" in r.stdout, r.stdout


def test_shadowing_module_is_neutralised(tmp_path):
    """The real failure mode: a foreign build of a dependency winning the import."""
    foreign = tmp_path / "lib" / OTHER / "site-packages"
    (foreign / "PIL").mkdir(parents=True)
    (foreign / "PIL" / "__init__.py").write_text(
        "raise ImportError('foreign Pillow built for another ABI')")

    assert run("from PIL import Image", str(foreign)).returncode != 0, \
        "fixture is wrong: the decoy did not shadow the real Pillow"

    r = run("import cachyview; from PIL import Image;"
            "print('PIL OK', Image.new('RGB', (4, 4)).size)", str(foreign))
    assert r.returncode == 0, f"guard failed to neutralise the decoy: {r.stderr}"
    assert "PIL OK (4, 4)" in r.stdout, r.stdout
