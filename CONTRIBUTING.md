# Contributing to CachyView

Thanks for taking an interest in CachyView! This document explains how to get
set up, the project's conventions, and how changes reach a release.

## Code of conduct

Be respectful and constructive. This is a small, focused project; assume good
intent and keep discussions on the technical merits.

## Getting set up

CachyView targets **Python 3.11+** and **Qt 6**. On CachyOS (or any Arch
derivative) the fast path is:

```bash
sudo pacman -S --needed base-devel git python python-pyqt6 python-pillow \
    python-pymupdf python-pikepdf python-ocrmypdf img2pdf \
    libvips 7zip unrar ghostscript qpdf poppler tesseract
python -m venv .venv --system-site-packages
. .venv/bin/activate
pip install -e ".[dev]"
pytest                       # should be green
```

The `--system-site-packages` venv is intentional: the distro PyQt6/Pillow are
built for the system interpreter and must be reused (a fresh venv cannot import
them). The test suite runs headless, so no display is required.

## Architecture

- `cachyview/backends/` — pure-Python, **Qt-free** logic for archives, images,
  PDFs and text. These are unit-tested against real files and reused by both
  the GUI and the CLI.
- `cachyview/ui/` — PyQt6 widgets, one tab per file kind plus tool dialogs.
- `cachyview/core/` — jobs, sandboxing, MIME routing, dependency probing.
- `cachyview/integration/` — the `cachyview-cli` command and `.desktop` /
  Dolphin service-menu installers.

**Rules (also in `README.md`):**

1. Backends never import Qt.
2. Every long operation is a cancellable job with progress; the UI never blocks.
3. No constructor opens a modal dialog (a corrupt/encrypted file sets an error
   state instead).
4. Optional dependencies are probed at runtime; a missing tool greys out one
   feature, never crashes.

## Before you open a pull request

- Run `pytest` and make sure it is green.
- Add or update tests for any behaviour change.
- Keep commits focused; write messages in the imperative ("add X", "fix Y").

## Releases

Maintainers cut releases from `main` by pushing a tag `vMAJOR.MINOR.PATCH`.
GitHub Actions then builds the installable bundle and publishes a release with
auto-generated notes. You do not need to build the package yourself — just open
a PR against `main`.

## Reporting bugs

Open an issue with: your distro, CachyView version (`cachyview --version` or
the About box), the file type involved, and the steps to reproduce. If you can
share a sample file, attach it (sanitised of anything private).
