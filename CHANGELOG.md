# Changelog

All notable changes are documented here. This project adheres to
[Semantic Versioning](https://semver.org/).

Release notes for each version are also generated automatically on the
[GitHub Releases page](https://github.com/mayankmohan1992/cachyview/releases).

## [Unreleased]

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
