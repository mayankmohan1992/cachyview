# Maintainer: mayankmohan1992 <mayankmohan1992@users.noreply.github.com>
# Contributors welcome — see https://github.com/mayankmohan1992/cachyview/CONTRIBUTING.md

pkgname=cachyview
pkgver=0.1.0
pkgrel=1
pkgdesc="Fast native archive, PDF, image and text toolkit for Linux — the offline, privacy-first alternative to macOS Preview."
arch=('x86_64' 'aarch64')
url="https://github.com/mayankmohan1992/cachyview"
license=('MIT')
# Runtime deps. PyQt6/Pillow come from the distro (the app reuses them via a
# --system-site-packages venv); the PDF engine libs are pip-installed into that
# venv at build time. ocrmypdf/ghostscript/etc. are invoked as subprocesses.
depends=(
  'python'
  'python-pyqt6'
  'python-pillow'
  'python-zstandard'  # tar.zst creation (Python tarfile needs the module)
  'python-ocrmypdf'   # provides the `ocrmypdf` binary the CLI shells out to
  'ghostscript'
  'qpdf'
  'poppler'
  'tesseract'
  'p7zip'
  'unrar'
  'libvips'
)
makedepends=(
  'python-pip'
  'python-setuptools'
)
provides=('cachyview')
conflicts=('cachyview-git')

source=("$pkgname-$pkgver.tar.gz::https://github.com/mayankmohan1992/cachyview/archive/refs/tags/v$pkgver.tar.gz")
sha256sums=('0a391d5ea8c2f59f2d0e883ef0fcf5dde0789908b33d4472011b64292199f8c3')

build() {
  # The app builds a --system-site-packages venv at install time; nothing to
  # compile ahead of time.
  :
}

package() {
  cd "$srcdir/$pkgname-$pkgver"

  APP_DIR="$pkgdir/usr/share/cachyview"
  BIN_DIR="$pkgdir/usr/bin"
  mkdir -p "$APP_DIR" "$BIN_DIR"

  # 1. App sources + metadata
  cp -r cachyview "$APP_DIR/cachyview"
  cp pyproject.toml "$APP_DIR/"

  # 2. Self-contained venv that reuses the distro PyQt6/Pillow.
  /usr/bin/python3 -m venv --system-site-packages "$APP_DIR/venv"
  "$APP_DIR/venv/bin/python" -m pip install --no-warn-script-location \
      "PyMuPDF" "pikepdf" "img2pdf" "pygments"

  SITE_DIR="$("$APP_DIR/venv/bin/python" -c 'import sysconfig; print(sysconfig.get_path("purelib"))')"
  echo "$APP_DIR" > "$SITE_DIR/cachyview.pth"
  "$APP_DIR/venv/bin/python" -c "import cachyview" \
      || { error "cachyview is not importable from the built venv"; return 1; }

  # 3. Launcher scripts (strip foreign env vars that can break PyQt/Pillow)
  cat > "$BIN_DIR/cachyview" <<EOF
#!/usr/bin/env bash
exec env -u PYTHONPATH -u PYTHONHOME -u VIRTUAL_ENV \\
    "$APP_DIR/venv/bin/python" -m cachyview "\$@"
EOF
  cat > "$BIN_DIR/cachyview-cli" <<EOF
#!/usr/bin/env bash
exec env -u PYTHONPATH -u PYTHONHOME -u VIRTUAL_ENV \\
    "$APP_DIR/venv/bin/python" -m cachyview.integration.cli "\$@"
EOF
  chmod 755 "$BIN_DIR/cachyview" "$BIN_DIR/cachyview-cli"

  # 4. .desktop entry — generated from the app's own template so it stays in sync.
  "$APP_DIR/venv/bin/python" - <<PY > "$srcdir/cachyview.desktop"
from cachyview.integration.desktop import desktop_entry
print(desktop_entry("/usr/bin/cachyview"))
PY
  install -Dm644 "$srcdir/cachyview.desktop" \
      "$pkgdir/usr/share/applications/cachyview.desktop"

  # 5. License
  install -Dm644 LICENSE "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}
