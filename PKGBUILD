# Maintainer: mayankmohan1992 <mayankmohan1992@users.noreply.github.com>
# Contributors welcome — see https://github.com/mayankmohan1992/cachyview/CONTRIBUTING.md

pkgname=cachyview
pkgver=0.3.0
pkgrel=1
pkgdesc="Fast native archive, PDF, image and text toolkit for Linux — the offline, privacy-first alternative to macOS Preview."
arch=('x86_64' 'aarch64')
url="https://github.com/mayankmohan1992/cachyview"
license=('MIT')
depends=(
  'python'
  'python-pyqt6'
  'qt6-svg'            # QSvgWidget for the SVG tab
  'python-pillow'
  'python-pymupdf'     # PDF rendering and editing
  'python-pikepdf'     # lossless PDF structure operations
  'python-zstandard'   # tar.zst creation (Python tarfile needs the module)
)
optdepends=(
  'python-pygments: syntax highlighting in the text viewer'
  'python-img2pdf: lossless image-to-PDF embedding'
  'python-numpy: faster PDF page comparison'
  '7zip: 7z/zip/rar archive extraction (required for most archives)'
  'unrar: RAR5 and encrypted RAR archives'
  'libvips: fast image scaling and conversion'
  'ghostscript: PDF compression and PDF/A export'
  'qpdf: PDF repair, linearize and encryption'
  'poppler: extra PDF rendering fallback'
  'tesseract: OCR engine'
  'ocrmypdf: searchable PDFs via OCR'
  'imagemagick: exotic image formats and operations'
  'inkscape: SVG conversion and export'
  'libreoffice-fresh: Office and PDF-to-Word conversion'
  'libwebp: WebP encoding (cwebp)'
  'oxipng: lossless PNG optimisation'
  'jpegoptim: lossless JPEG optimisation'
  'python-pillow-heif: HEIC/HEIF photos'
  'python-pillow-avif: AVIF images'
  'python-pillow-jxl: JPEG XL images'
  'python-rawpy: camera RAW decoding'
  'python-lz4: LZ4 archives and .tar.lz4'
)
makedepends=(
  'python-build'
  'python-installer'
  'python-wheel'
  'python-setuptools'
)
provides=('cachyview')
conflicts=('cachyview-git')

source=("$pkgname-$pkgver.tar.gz::https://github.com/mayankmohan1992/cachyview/archive/refs/tags/v$pkgver.tar.gz")
# The tarball is created by the release workflow; update this once v$pkgver is
# tagged (tools/release prints the checksum).
sha256sums=('SKIP')

build() {
  cd "$srcdir/$pkgname-$pkgver"
  # Build a wheel without network access; deps come from the packages above.
  python -m build --wheel --no-isolation
}

package() {
  cd "$srcdir/$pkgname-$pkgver"

  # 1. Python package + console scripts (cachyview, cachyview-cli)
  python -m installer --destdir="$pkgdir" dist/*.whl

  # 2. Desktop entry, AppStream metadata, Dolphin service menus, thumbnailer
  #    and icon — generated from the app's own templates so they never drift.
  SITE_DIR="$(python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')"
  PYTHONPATH="$pkgdir$SITE_DIR" python - "$pkgdir" <<'PY'
import pathlib
import sys

from cachyview.integration import desktop

pkg = pathlib.Path(sys.argv[1])
gui, cli = "/usr/bin/cachyview", "/usr/bin/cachyview-cli"


def put(rel: str, name: str, content: str, mode: int = 0o644) -> None:
    target = pkg / rel / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    target.chmod(mode)


put("usr/share/applications", f"{desktop.DESKTOP_ID}.desktop",
    desktop.desktop_entry(gui))
put("usr/share/metainfo", f"{desktop.DESKTOP_ID}.metainfo.xml",
    desktop.metainfo_xml())
for name, content in {
    "cachyview-archive.desktop": desktop.archive_menu(gui, cli),
    "cachyview-pdf.desktop": desktop.pdf_menu(gui, cli),
    "cachyview-image.desktop": desktop.image_menu(gui, cli),
}.items():
    put("usr/share/kio/servicemenus", name, content, 0o755)
put("usr/share/thumbnailers", "cachyview.thumbnailer",
    desktop.thumbnailer_entry(cli))

icon = pathlib.Path(desktop.__file__).resolve().parents[1] / "data" / "cachyview.svg"
put("usr/share/icons/hicolor/scalable/apps", "cachyview.svg",
    icon.read_text(encoding="utf-8"))
PY

  # 3. License
  install -Dm644 LICENSE "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}
