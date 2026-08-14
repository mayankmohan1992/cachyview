#!/usr/bin/env bash
# Build a portable CachyView install bundle into $1 (a directory).
#
# Unlike install.sh (which reuses the *distro* PyQt6 via --system-site-packages
# for speed on CachyOS), this script builds a self-contained virtualenv with
# PyQt6 installed from PyPI. The result is portable to any Linux machine that
# has the runtime Qt libraries (see README "System dependencies").
#
# Usage: tools/bundle.sh /path/to/output/cachyview
set -euo pipefail

OUT="$(readlink -f "${1:?usage: tools/bundle.sh <output-dir>}")"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON:-python3}"

echo "→ Building CachyView bundle in: $OUT"
rm -rf "$OUT"
mkdir -p "$OUT"

# 1. App sources + packaging metadata
cp -r "$SRC_DIR/cachyview" "$OUT/cachyview"
cp "$SRC_DIR/pyproject.toml" "$OUT/pyproject.toml"
cp "$SRC_DIR/LICENSE" "$OUT/LICENSE" 2>/dev/null || true
cp "$SRC_DIR/README.md" "$OUT/README.md" 2>/dev/null || true

# 2. Self-contained virtualenv with PyQt6 from PyPI
"$PY" -m venv "$OUT/venv"
VENV_PY="$OUT/venv/bin/python"
"$VENV_PY" -m pip install --quiet --upgrade pip
"$VENV_PY" -m pip install --quiet \
    "PyQt6" "Pillow" "PyMuPDF" "pikepdf" "img2pdf" "pygments"

# 3. Put the app on the venv import path via a .pth (no build backend needed)
SITE_DIR="$("$VENV_PY" -c 'import sysconfig; print(sysconfig.get_path("purelib"))')"
echo "$OUT" > "$SITE_DIR/cachyview.pth"
"$VENV_PY" -c "import cachyview" || { echo "app not importable"; exit 1; }

# 4. Launcher scripts (strip foreign env vars that can break PyQt/Pillow)
BIN="$OUT"
cat > "$BIN/cachyview" <<EOF
#!/usr/bin/env bash
exec env -u PYTHONPATH -u PYTHONHOME -u VIRTUAL_ENV \\
    "$OUT/venv/bin/python" -m cachyview "\$@"
EOF
cat > "$BIN/cachyview-cli" <<EOF
#!/usr/bin/env bash
exec env -u PYTHONPATH -u PYTHONHOME -u VIRTUAL_ENV \\
    "$OUT/venv/bin/python" -m cachyview.integration.cli "\$@"
EOF
chmod +x "$BIN/cachyview" "$BIN/cachyview-cli"

echo "→ Bundle built at: $OUT"
"$OUT/cachyview" --check-deps || true
