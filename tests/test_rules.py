"""Static guards for the project's documented design rules.

These are cheap, deterministic checks that keep the architecture honest:
rule 1 (backends stay Qt-free) and rule 5 (subprocesses go through the
scrubbed argv-only runner in ``core/process.py``).
"""
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent / "cachyview"


def _source_files(*parts: str) -> list[Path]:
    root = PKG.joinpath(*parts)
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def test_backends_never_import_qt():
    offenders = []
    for path in _source_files("backends"):
        text = path.read_text(encoding="utf-8")
        if "PyQt" in text or "from PyQt6" in text:
            offenders.append(str(path.relative_to(PKG.parent)))
    assert not offenders, f"backends must stay Qt-free: {offenders}"


def test_subprocess_only_used_in_process_runner():
    offenders = []
    needles = ("subprocess.run(", "subprocess.Popen(", "subprocess.call(",
               "subprocess.check_output(", "subprocess.check_call(")
    for path in _source_files():
        if path.name == "process.py" and path.parent.name == "core":
            continue
        text = path.read_text(encoding="utf-8")
        if any(n in text for n in needles):
            offenders.append(str(path.relative_to(PKG.parent)))
    assert not offenders, (
        "every subprocess must go through core.process.run: " + ", ".join(offenders))
