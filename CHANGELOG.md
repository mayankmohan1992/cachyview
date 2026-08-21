# Changelog

All notable changes are documented here. This project adheres to
[Semantic Versioning](https://semver.org/).

Release notes for each version are also generated automatically on the
[GitHub Releases page](https://github.com/mayankmohan1992/cachyview/releases).

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
