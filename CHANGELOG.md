# Changelog

All notable changes are documented here. This project adheres to
[Semantic Versioning](https://semver.org/).

Release notes for each version are also generated automatically on the
[GitHub Releases page](https://github.com/mayankmohan1992/cachyview/releases).

## [Unreleased]

### Added
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

### Changed
- PDF toolbar redesigned to a Preview-style icon bar: instant in-place
  rotate / delete / insert, an Annotate popup, and a Tools overflow menu.

### Fixed
- Selection of external tools no longer inherits a foreign `PYTHONPATH`.
