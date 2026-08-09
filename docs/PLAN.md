# CachyView — a Preview.app-class toolkit for CachyOS/KDE

## 0. Goal
One fast native app that opens archives, PDFs, images and text; edits them;
and exposes the same actions from the Dolphin context menu.

## 1. Tech stack (decided from what CachyOS already ships)

| Layer | Choice | Why |
|---|---|---|
| UI | **PyQt6 / Qt 6.11 Widgets** (already installed) | native Plasma look, no Electron, ~60MB RSS, fastest path to a feature-rich UI |
| PDF render | **PyMuPDF (MuPDF)** primary, poppler-qt6 fallback | fastest renderer; text edit, redaction, annotation, OCR hooks |
| PDF structural ops | **qpdf/pikepdf** (split/merge/rotate/encrypt/linearize) | lossless, no re-render |
| PDF compress | **Ghostscript** presets + PyMuPDF image downsample | matches iLovePDF quality tiers |
| PDF OCR | **ocrmypdf + tesseract** | searchable PDFs |
| Office→PDF | **libreoffice --headless** (optional dep) | docx/xlsx/pptx conversion |
| Archives | **libarchive** (zip/7z/tar/gz/xz/zst/iso/cab) + **7z CLI** + **unrar** for RAR5 & encrypted | libarchive can't do encrypted 7z/RAR reliably → CLI fallback |
| Images | **Pillow + libvips (optional) + ImageMagick CLI** for exotic ops | raster edit pipeline |
| Vector | **Qt SVG render + Inkscape CLI** (optional) for SVG↔PNG/PDF | no need to reimplement Inkscape |
| RAW/HEIC | libraw / libheif via Pillow plugins | optional deps |
| Shell integration | **KDE ServiceMenus** (`.desktop` in `~/.local/share/kio/servicemenus/`) + MIME + thumbnailer | native Dolphin context menu, zero C++ plugin |
| Packaging | PKGBUILD → local repo; run from venv-free system python | CachyOS-native, easy rollback |
| Perf | QThreadPool workers, page cache, lazy archive listing, mmap'd render | UI never blocks |

Rejected: Electron/Tauri (heavy / duplicate stack), GTK (non-native on Plasma),
writing our own PDF parser (insane), embedding GIMP/Inkscape (huge; we shell out instead).

## 2. Feature matrix

### 2.1 Archive module
- Open zip, 7z, rar(+rar5), tar(.gz/.bz2/.xz/.zst/.lz4), iso, cab, ar, cpio, deb, rpm, gz/xz single-file
- Tree + flat view, size/ratio/mtime/CRC columns, search filter
- Password prompt (retry loop, per-session cache, encrypted-header support)
- Click file → extract to temp → open in the matching internal viewer (PDF/image/text) — no external app
- Extract selected / extract all / drag-out to Dolphin
- Create & add-to archive (zip/7z/tar.zst), set compression level + password
- Delete/rename inside archive where format allows
- Nested archive open-in-place
- Integrity test, comment view

### 2.2 PDF module (iLovePDF/PDF24 parity)
Viewer: continuous scroll, zoom/fit, thumbnails sidebar, outline/TOC, text select+copy,
search, dark/invert mode, presentation mode, form filling, annotation (highlight,
note, freehand, shapes), signature (image or drawn), page text editing (basic).

Tools: merge · split (by range/every-N/bookmarks) · extract pages · delete/reorder/rotate
pages (drag-drop page organizer) · compress (screen/ebook/printer/prepress) · crop ·
watermark (text/image) · page numbers · header/footer · N-up · booklet ·
protect/unlock (AES-256) · permissions · flatten · linearize · repair · redact ·
metadata edit · OCR · compare (side-by-side diff).

Convert: → images (png/jpg/tiff @ DPI), → text, → HTML, → docx (optional via LibreOffice),
images → PDF, office → PDF, text/markdown → PDF, PDF/A output.

### 2.3 Image module
Viewer: fast pan/zoom, next/prev in folder, EXIF panel, histogram, slideshow, filmstrip,
animated GIF/WebP/APNG, SVG, RAW, HEIC/AVIF/JXL (optional deps), multi-page TIFF.

Edit (GIMP-lite, non-destructive stack + undo): crop, rotate/flip, straighten, resize/
resample, canvas resize, color: brightness/contrast/exposure/gamma/saturation/hue/
temperature/levels/curves/auto-tone, B&W & filters, sharpen/blur/denoise, red-eye,
text overlay, draw/annotate, watermark, background removal (rembg, optional),
compare-before/after.

Batch: convert format, resize, rename, watermark, strip/keep EXIF, compress
(mozjpeg/oxipng/cwebp/avifenc when present).

Vector (SVG): view, source edit with live preview, convert to PNG/PDF/EPS via Inkscape CLI,
optimize via svgo/scour (optional).

### 2.4 Text module
Syntax highlight (QSyntaxHighlighter/pygments), line numbers, find/replace w/ regex,
encoding + line-ending switch, large-file streaming, markdown live preview,
hex view for binaries, JSON/XML/YAML pretty-print & validate, diff two files.

### 2.5 Shell / desktop integration
- `cachyview <file>` CLI; single-instance D-Bus, tabs
- Dolphin service menus, context-aware by MIME:
  - archives: Open in CachyView / Extract here / Extract to… / Test
  - multi-select PDFs: Merge…; single PDF: Compress / Split / Rotate / Protect / OCR / To images
  - multi-select images: Convert to PDF / Batch resize / Batch convert
  - any: Open with CachyView
- MIME + .desktop registration, optional default-app takeover (opt-in), thumbnailer
- Everything also available as `cachyview-cli` subcommands for scripting

## 3. Architecture
```
cachyview/
  core/        job runner (QThreadPool), temp/sandbox mgr, mime detect, settings, plugin registry
  backends/    archive/ pdf/ image/ text/  ← pure-python, no Qt, unit-testable, CLI-usable
  ui/          main window, tabbed doc area, per-type viewer widgets, tool dialogs, organizer
  integration/ servicemenus, mime xml, thumbnailer, cli
  tests/
```
- Backends never touch Qt → same code powers GUI + CLI + context menu.
- Every long op = a Job object with progress/cancel; UI subscribes.
- Optional deps are probed at runtime; missing tool → feature greyed out with a
  one-click "install with paru" hint, never a crash.

## 4. Security
- Archive extraction: path traversal (`../`, absolute, symlink escape) rejected;
  extract into a per-session dir under `$XDG_RUNTIME_DIR`, 0700, auto-purged.
- Zip-bomb guard: ratio + total-size + entry-count caps, cancellable.
- Passwords held in memory only (never argv — passed via stdin/env to 7z/unrar).
- No network calls at all (no telemetry, no update pings).
- External tools invoked with argv lists, never shell strings.
- PDF JS/embedded-file execution disabled; external links confirm before opening.

## 5. Milestones
1. Skeleton: core job runner, MIME routing, tabbed shell, text viewer, settings
2. Image viewer + basic edits + batch
3. Archive module (read/extract/password/nested) then write support
4. PDF viewer + organizer + top-10 tools
5. Remaining PDF tools, OCR, convert matrix, annotations/signature
6. Image advanced edit stack, SVG, RAW/HEIC
7. Dolphin service menus, MIME, thumbnailer, CLI
8. Perf pass, fuzz/security tests, PKGBUILD + rollback script
```
