# CachyView

A fast, native archive / PDF / image / text toolkit for CachyOS — the Preview.app
and iLovePDF replacement that stays on your machine.

- **No network access.** Ever. No telemetry, no update pings.
- **Native Qt 6**, not Electron. Starts fast, stays light.
- **Everything scriptable**: the GUI, the `cachyview-cli` command and the Dolphin
  right-click menu all call the same pure-Python backends.

## Install

```bash
./install.sh              # user-only; no root, nothing outside ~/.local
./install.sh --uninstall  # removes every file it created
```

Then `cachyview <file>`, pick it from the application menu, or right-click a
file in Dolphin.

## Features

### Archives
zip · 7z · rar (incl. RAR5) · tar/gz/bz2/xz/zst · iso · cab · deb · rpm

Browse as a tree with sizes and timestamps, filter, double-click a file to open
it in the matching viewer, extract all or selected, test integrity, create new
archives. Password-protected archives are supported, including 7z with encrypted
headers.

### PDF
View with thumbnails, outline, text search and zoom. Tools: merge · split ·
extract / delete / rotate / reorder pages · compress (4 Ghostscript tiers) ·
AES-256 protect and unlock · repair · watermark · page numbers · metadata ·
OCR (searchable text via tesseract) · convert to images or text · build from
images.

### Images
View with zoom, pan and EXIF. Edit non-destructively (every change is an
undoable operation applied to the original): rotate · flip · crop · resize ·
scale · brightness · contrast · saturation · sharpness · grayscale · invert ·
auto-contrast · blur · sharpen · border. Batch convert and combine into PDF.

### Text
Syntax-aware editor with line numbers, find, JSON/XML pretty-printing, encoding
and line-ending detection, and atomic saves.

## Command line

```bash
cachyview-cli list archive.7z
cachyview-cli extract *.zip -d ~/unpacked
cachyview-cli pdf compress report.pdf --tier screen
cachyview-cli pdf split report.pdf --every 10
cachyview-cli pdf ocr scan.pdf --language eng
cachyview-cli image convert *.heic -f jpg --resize 1920
cachyview-cli image to-pdf page*.png -o album.pdf
```

## Test

```bash
pytest                          # self-configuring; runs headless
python tools/shot.py out/       # render each viewer for visual review
cachyview --check-deps          # what optional features are available
```

## Design rules

1. Backends never import Qt, so they are unit-testable and reusable from the CLI.
2. Every long operation is a cancellable job with progress; the UI never blocks.
3. No constructor opens a modal dialog — a corrupt or encrypted file sets an
   error state instead, so headless and service-menu use can never hang.
4. Optional dependencies are probed at runtime; a missing tool greys out one
   feature and shows the install command instead of crashing.
5. Subprocesses get argv lists (never a shell) and a scrubbed environment.
6. Archive extraction is sandboxed with path-traversal, symlink-escape and
   decompression-bomb guards.

### Known limitation

Archive passwords are passed to `7z`/`unrar` as command-line arguments, so they
are briefly visible in `/proc` to other processes of the same user. Neither tool
can read a password from a pipe — both demand a terminal — so there is no better
option short of bundling our own crypto. Plain zips handled by the built-in
Python fallback never expose the password.

## Layout

```
cachyview/
  core/         jobs, sandbox, MIME routing, dependency probe, subprocess
  backends/     archive, image, pdf, text   (no Qt, importable anywhere)
  ui/           main window and one tab per file kind, plus tool dialogs
  integration/  CLI, .desktop entry, Dolphin service menus
tests/          301 tests against real files
```
