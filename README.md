# CachyView

**A fast, native archive · PDF · image · text toolkit for Linux — the
lightweight, offline, privacy-first alternative to macOS Preview and the
online "PDF toolbox" sites.**

CachyView is built on **Qt 6** and **MuPDF**, not Electron. It starts in a
fraction of a second, stays light on memory, and **never touches the network** —
no telemetry, no update pings, no files uploaded. Everything runs locally on
your machine.

- 🖼 **Images** — folder filmstrip, slideshow, EXIF inspector; non-destructive
  Adjust Color sliders; crop, resize, canvas, straighten; classic filters
  (blur, unsharp, sepia, vignette — no AI); markup; export with quality.
- 📕 **PDF** — continuous scroll, thumbnails + outline, text search, copy,
  print; markup saved *inside* the file on Save; redaction; signatures;
  in-place rotate/delete/insert; Tools menu for merge, split, compress,
  protect, OCR, watermark, N-up, booklet, PDF/A, Word export and more.
- 🗜 **Archives** — tree with size/ratio/CRC, preview pane, extract, test,
  create/add/delete/rename; sandbox-hardened extraction; comic mode for cbz.
- 📝 **Text** — syntax highlighting, find/replace, encoding/line-ending,
  markdown & CSV views, hex viewer for binaries.
- ➰ **SVG** — dedicated vector viewer with an editable source pane and live
  preview (Qt SVG, no external renderer).

> Why "CachyView"? It started as a CachyOS-centric tool, but it runs on any
> modern Linux desktop with Qt 6.

---

## Quick start (CachyOS / Arch)

```bash
git clone https://github.com/mayankmohan1992/cachyview.git
cd cachyview
./install.sh            # user-only; no root, nothing outside ~/.local
```

Then launch it from your application menu (**CachyView** under *Graphics*),
run `cachyview <file>` from a terminal, or right-click a file in Dolphin.
It also appears in Discover / software centres via AppStream metadata.

To make CachyView the default handler for PDFs, images, archives and text:

```bash
cachyview --set-default all      # or: pdf images archives text
```

To remove everything the installer created: `./install.sh --uninstall`.

### System dependencies (Arch / CachyOS)

```bash
sudo pacman -S --needed python python-pyqt6 python-pillow python-pymupdf \
    python-pikepdf python-ocrmypdf img2pdf libvips 7zip unrar \
    ghostscript qpdf poppler tesseract
```

`python-pyqt6` and `python-pillow` are required; the rest unlock optional
features (PDF engine, OCR, compression tiers, archive formats). Missing tools
are detected at runtime and only grey out the one feature that needs them.

### Optional file formats

A few formats need extra decoders. Without them the file still opens into a
clear "install this package" message instead of failing silently:

```bash
paru -S --needed python-pillow-heif python-pillow-avif python-pillow-jxl \
    python-rawpy python-lz4 python-yaml
```

| Format | Package | Feature |
|---|---|---|
| HEIC / HEIF | `python-pillow-heif` | phone photos |
| AVIF | `python-pillow-avif` | AVIF images |
| JPEG XL | `python-pillow-jxl` | JXL images |
| Camera RAW (CR2/NEF/ARW/DNG/…) | `python-rawpy` | RAW decoding |
| LZ4 (`.lz4`, `.tar.lz4`) | `python-lz4` | LZ4 archives |
| YAML | `python-yaml` | YAML format / validate in the text tab |

SVG is rendered by Qt itself and needs no extra package.

---

## Install on other Linux distributions

CachyView is distro-agnostic — it needs Python 3.11+ and Qt 6. The
`install.sh` script assumes an Arch-style layout (it uses a
`--system-site-packages` venv so the **distro** PyQt6/Pillow are reused), which
is the recommended setup on CachyOS. On other distributions:

### Fedora

```bash
sudo dnf install python3-qt6 python3-pillow python3-PyMuPDF python3-pikepdf \
    python3-ocrmypdf img2pdf vips-tools p7zip unrar ghostscript qpdf \
    poppler-utils tesseract
git clone https://github.com/mayankmohan1992/cachyview.git && cd cachyview
python3 -m venv .venv --system-site-packages
. .venv/bin/activate
pip install -e .
cachyview            # or: python -m cachyview
```

### Debian / Ubuntu (24.04+ for PyQt6)

```bash
sudo apt install python3-pyqt6 python3-pil python3-fitz python3-pikepdf \
    ocrmypdf img2pdf libvips-tools p7zip-full unrar ghostscript qpdf \
    poppler-utils tesseract-ocr
git clone https://github.com/mayankmohan1992/cachyview.git && cd cachyview
python3 -m venv .venv --system-site-packages
. .venv/bin/activate
pip install -e .
cachyview
```

> **Note on PyQt6 from pip:** if your distro does not package PyQt6 (or you
> prefer a self-contained install), you may `pip install pyqt6 pillow` into a
> normal venv instead of using `--system-site-packages`. The app behaves
> identically; you just trade the distro build for a pip one.

### From the GitHub Releases page

Each release on the
[Releases tab](https://github.com/mayankmohan1992/cachyview/releases) ships a
ready-to-run bundle:

1. Download `cachyview-<version>-linux.tar.zst`.
2. Extract it: `tar --zstd -xf cachyview-*.tar.zst`.
3. Run `./cachyview/cachyview` (or copy it somewhere on your `PATH`).

The bundle is fully portable and needs only the runtime libraries listed above.

---

## Build from source

For development or packaging:

```bash
python3 -m venv .venv --system-site-packages
. .venv/bin/activate
pip install -e ".[dev]"     # adds pytest
pytest                      # headless test suite, ~550 tests
```

The GUI is exercised headlessly in CI; no display is required to run the
tests.

---

## Command line

The same backends power a CLI (`cachyview-cli`):

```bash
cachyview-cli list archive.7z
cachyview-cli extract *.zip -d ~/unpacked
cachyview-cli pdf compress report.pdf --tier screen
cachyview-cli pdf split report.pdf --every 10
cachyview-cli pdf nup report.pdf --per-sheet 2
cachyview-cli pdf booklet report.pdf
cachyview-cli pdf to-html report.pdf
cachyview-cli pdf watermark report.pdf --text DRAFT
cachyview-cli pdf ocr scan.pdf --language eng
cachyview-cli image convert *.heic -f jpg --resize 1920
cachyview-cli image to-pdf page*.png -o album.pdf
cachyview-cli thumbnail report.pdf thumb.png --size 256
```

Run `cachyview-cli --help` for the full list.

---

## Design rules

1. Backends never import Qt, so they are unit-testable and reusable from the CLI.
2. Long operations run as cancellable background jobs with progress (extraction,
   batch, preview, PDF tools, archive listing).
3. No constructor opens a modal dialog — a corrupt or encrypted file sets an
   error state instead, so headless and service-menu use can never hang.
4. Optional dependencies are probed at runtime; a missing tool greys out one
   feature and shows the install command instead of crashing.
5. Subprocesses get argv lists (never a shell) and a scrubbed environment.
6. Archive extraction is sandboxed with path-traversal, symlink-escape and
   decompression-bomb guards (ratio, total-size and entry-count caps).
7. PDF JavaScript and embedded files are never executed; external links ask
   for confirmation and only `http(s)`, `mailto` and `file` are allowed.

### Known limitations

- Archive passwords are passed to `7z`/`unrar` as command-line arguments, so
  they are briefly visible in `/proc` to other processes of the same user.
  Neither tool can read a password from a pipe — both demand a terminal — so
  there is no better option short of bundling our own crypto. Plain zips
  handled by the built-in Python fallback never expose the password.
- Cryptographic signing with a PKCS#12 certificate is not implemented (a
  visual signature stamp is). PDF→DOCX, PDF/A, PDF→HTML, text/Markdown→PDF,
  N-up, booklet and linearize are.


---

## Project layout

```
cachyview/
  core/         jobs, sandbox, MIME routing, dependency probe, subprocess
  backends/     archive, image, pdf, text   (no Qt, importable anywhere)
  ui/           main window and one tab per file kind, plus tool dialogs
  integration/  CLI, .desktop entry, Dolphin service menus, KDE thumbnailer
tests/          ~550 tests against real files
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Bug reports and PRs are welcome.

## License

[MIT](LICENSE). CachyView is free software.
