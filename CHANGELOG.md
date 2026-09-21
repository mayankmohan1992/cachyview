# Changelog

All notable changes are documented here. This project adheres to
[Semantic Versioning](https://semver.org/).

Release notes for each version are also generated automatically on the
[GitHub Releases page](https://github.com/mayankmohan1992/cachyview/releases).

## [0.3.0] - 2026-09-21

### Fixed
- PDF **redaction** now affects only the page the mark was drawn on (it used
  to be applied to every page sharing the box origin).
- **Images → PDF** no longer overwrites the source image when rotating an
  arranged page; rotations go to private temp copies.
- Archive **Edit** actions (add/delete/rename) are disabled for formats 7-Zip
  cannot rewrite (`.rar`, single-file `.gz`/`.xz`/`.bz2`/`.zst`).
- Inserting an image into a PDF now honours the requested position and the
  document password.
- Editing a PDF outline no longer risks a `NameError` masking the real error,
  and the write is cleaned up if it fails.
- PDF comparison returns diff images in memory instead of littering the source
  directory, reports "extra page(s)" correctly, and runs much faster.
- In-place batch runs keep a `name~` recovery copy of each original.
- Batch per-file updates are delivered on the GUI thread (were applied from a
  worker thread).
- PDF **bookmark levels** now round-trip correctly and any edit list is
  normalised into a valid outline instead of raising a raw `ValueError`.
- The headless test suite is deterministic again: the host Qt platform theme
  is neutralised and cyclic GC is disabled, which stops the intermittent
  cross-module Qt segfault (exit 139).
- `install.sh` installs the PDF engine (PyMuPDF/pikepdf/img2pdf/pygments) into
  the app's virtualenv when the distro copy is missing or its native library is
  broken, so PDF support no longer silently disappears; the dependency probe
  now performs a real import instead of trusting `find_spec`.

### Added
- Dedicated **SVG** tab: vector preview plus editable source with live preview.
- HEIC/AVIF/JXL/RAW/LZ4 decode through optional packages, with a clear
  "install this" message when the decoder is missing.
- LZ4 archive support (`.lz4` and `.tar.lz4`) via `python-lz4`.
- PDF **N-up**, **booklet** imposition, **linearize**, **PDF → HTML** and
  **text/Markdown → PDF**; image watermarks; full title/author/subject/keywords
  metadata editing.
- PDF viewer **dark/invert view** (non-destructive), fullscreen **presentation**
  with keyboard navigation, and previous-match search.
- Image **histogram** panel, **watermark** (image/text), resize resample/aspect
  options, real animation frame timings, and batch **rename patterns** with
  EXIF keep/strip control.
- Archive **flat view**, archive comment viewer, compressed-tar compression
  levels, `tar.bz2` creation, and a proper comic page-through mode.
- KDE shell **thumbnailer** for PDFs/images, a generic "Open with CachyView"
  service menu, and new `cachyview-cli` commands (`thumbnail`, `pdf nup`,
  `booklet`, `linearize`, `to-html`, `watermark`).
- YAML formatting and a JSON/XML/TOML/YAML **Validate** action in the text tab.
- Image **levels** and **curves** adjustments (non-destructive, with live
  sliders) and **red-eye removal**.
- PDF **→ Word (.docx)** and **PDF/A** export (LibreOffice / Ghostscript).
- Full bookmark CRUD in the outline editor (edit an existing entry in place).
- **AppStream metadata** and a reverse-DNS app id (`org.cachyview.CachyView`),
  so CachyView is listed in Discover and other software centres.
- `cachyview --set-default [pdf|images|archives|text|all]` and `--version`.

### Security
- Archive extraction: **entry-count cap**, cooperative **cancellation** for
  both Python and external-tool extraction, and isolation through a staging
  directory that **drops symlinks** before files reach the user.
- All subprocesses now go through the scrubbed-environment runner.
- PDF external links require confirmation and only `http(s)`/`mailto`/`file`
  schemes are allowed; JavaScript and embedded files are never executed.

### Changed
- Reconcile README/PLAN/SECURITY with the shipped feature set; the PKGBUILD
  ships the Dolphin service menus and AppStream metadata.
- Atomic writes for settings, recents and image-edit history; LRU page cache
  in the PDF viewer; lint (ruff) added to CI.
- Archive listing now runs on a background job, so the UI never blocks on it.
- PKGBUILD rewritten to Arch policy: distro packages in `depends`, tooling in
  `optdepends`, no network access in `package()`, and it installs the AppStream
  metadata. CI now also tests on an Arch container (the CachyOS target).


## [0.2.0] - 2026-08-21

### Added
- PDF page **Crop & Resize** (trim margins, normalise to A4/Letter/Legal/A3/A5).
- PDF **Invert colours** for dark-mode reading.
- PDF **Headers & Footers** with optional page numbers.
- File **Fingerprint** (SHA-256 / SHA-1 / MD5) for integrity verification.
- **Images → PDF** with a visual drag-and-drop grid to arrange page order
  before combining (Tools ▸ Images to PDF…).

### Changed
- Theme icons replace emoji in the PDF/image chrome where the icon theme
  provides them; batch "resize 50%" now actually scales by half.

### Added
- PDF markup expansion: rectangle, oval, line, arrow and freehand sketch
  annotations, plus strikethrough — all saved inside the PDF.
- Sidebar toggle and a zoom slider in the PDF view.
- Thumbnail multi-select: delete / rotate / extract selected pages in place.
- Signatures: capture a freehand signature and click to place it on a page.
- GitHub Actions CI (multi-Python tests) and an automatic release workflow
  that builds a portable Linux bundle on every `v*` tag.
- Preview-class shell: single-instance hand-off, command palette (Ctrl+K),
  inspector sidebar, empty-state recents, Save As / Print / Open With /
  containing folder / share, and `--peek` Quick Look windows.
- Continuous scrolling PDF view, search hit navigation via MuPDF, copy page
  text, print, deferred annotation save, and AcroForm fill.
- Image Adjust Color sliders, resize/canvas/straighten dialogs, classic
  filters (blur, unsharp, median, sepia, vignette, … — no AI), pixel markup,
  folder filmstrip, slideshow, and export-with-quality.
- Text syntax highlighting, find/replace, encoding/newline pickers, markdown
  and CSV views, hex viewer for binaries, and a two-file text diff.
- Archive preview pane, CRC/ratio columns, add/delete/rename, create dialog,
  comic mode, and Dolphin Extract-To / Test / Compress fixes.

### Changed
- PDF toolbar redesigned to a Preview-style icon bar: instant in-place
  rotate / delete / insert, an Annotate popup, and a Tools overflow menu.

### Fixed
- Selection of external tools no longer inherits a foreign `PYTHONPATH`.
- `rotate_current` / `delete_current` now return the edit job so inline
  operations can be awaited.
- pikepdf outline / sketch-annotation regressions fixed.
- Plain `line` annotations no longer misread as `arrow`.
