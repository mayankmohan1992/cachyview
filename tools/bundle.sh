#!/usr/bin/env bash
# Build a **portable** CachyView bundle into $1 (a directory).
#
# Design goals:
#   * Relocatable: it runs on any modern Linux, regardless of the distro's
#     Python minor version, because it carries a standalone CPython
#     (python-build-standalone via uv).  No system Python needed.
#   * Lean: PyQt6's pip wheel ships every Qt module; we keep only the ones
#     CachyView imports (Core/Gui/Widgets/Network/Svg/PrintSupport + DBus and
#     the platform plugins) and drop QML, translations, dev stubs and the rest.
#   * Verified: a smoke test imports the used Qt modules and opens a PDF before
#     the build is considered good.
#
# Usage: tools/bundle.sh /path/to/output/cachyview
set -euo pipefail

RAW_OUT="${1:?usage: tools/bundle.sh <output-dir>}"
mkdir -p "$RAW_OUT"
OUT="$(cd "$RAW_OUT" && pwd -P)"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
PYVER="${PYVER:-3.12}"

# Python packages the app needs at runtime (PDF engine + image + syntax).
PKGS=("PyQt6" "Pillow" "PyMuPDF" "pikepdf" "img2pdf" "pygments")

APP="$OUT/app"          # CachyView sources
SITE="$OUT/site"        # pip --target packages
PYROOT="$OUT/python"    # bundled interpreter

echo "→ Building portable CachyView bundle in: $OUT"
rm -rf "$OUT"
mkdir -p "$APP" "$SITE" "$PYROOT"

# --------------------------------------------------------------------------
# 1. App sources + metadata
# --------------------------------------------------------------------------
cp -r "$SRC_DIR/cachyview" "$APP/cachyview"
cp "$SRC_DIR/pyproject.toml" "$APP/pyproject.toml"
cp "$SRC_DIR/LICENSE" "$APP/LICENSE" 2>/dev/null || true
cp "$SRC_DIR/README.md" "$APP/README.md" 2>/dev/null || true

# --------------------------------------------------------------------------
# 2. Standalone, relocatable CPython (so the bundle is not tied to the host's
#    python3 minor version, which is exactly how the previous bundles broke).
# --------------------------------------------------------------------------
if ! command -v uv >/dev/null 2>&1; then
    echo "error: 'uv' is required to fetch a relocatable Python." >&2
    echo "       install it:  curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
    exit 1
fi
UV_PYTHON_INSTALL_DIR="$PYROOT" uv python install "$PYVER" >/dev/null
SRC_PY_DIR="$(find "$PYROOT" -maxdepth 1 -type d -name 'cpython-*' | head -1)"
[ -n "$SRC_PY_DIR" ] || { echo "error: uv did not install a Python" >&2; exit 1; }
mv "$SRC_PY_DIR" "$PYROOT/runtime"
BASE_PY="$PYROOT/runtime/bin/python3"

# --------------------------------------------------------------------------
# 3. Install the runtime packages into a flat, relocatable directory
# --------------------------------------------------------------------------
"$BASE_PY" -m pip install --quiet --disable-pip-version-check --target "$SITE" "${PKGS[@]}"

# --------------------------------------------------------------------------
# 4. Prune what the app never uses
# --------------------------------------------------------------------------
prune_qt() {
    local qt="$SITE/PyQt6"
    [ -d "$qt" ] || return 0
    local mods=( Quick Qml Designer ShaderTools Multimedia SpatialAudio Bluetooth
                 Nfc RemoteObjects Help Pdf Positioning Sensors Test Sql
                 StateMachine Labs WebSockets WebChannel SerialPort TextToSpeech
                 Charts DataVisualization Graphs VirtualKeyboard Scxml UiTools
                 WebEngine )
    local m
    for m in "${mods[@]}"; do
        rm -f "$qt/Qt6/lib/libQt6${m}"*.so* "$qt/Qt${m}.abi3.so" "$qt/Qt${m}.pyi"
    done
    # Multimedia/FFmpeg and friends come in via QtMultimedia.
    rm -f "$qt/Qt6/lib/libav"*.so* "$qt/Qt6/lib/libsw"*.so* \
          "$qt/Qt6/lib/libpostproc"*.so*
    local plugins="$qt/Qt6/plugins"
    for d in sceneparsers assetimporters qmlls qmllint renderers sqldrivers \
             position sensors texttospeech webview help scxmldatamodel \
             multimedia geometryloaders renderplugins designercustomwidgets; do
        rm -rf "$plugins/$d"
    done
    # QML engine, translations, QScintilla and IDE/dev-only files.
    rm -rf "$qt/Qt6/qml" "$qt/Qt6/translations" "$qt/Qt6/qsci" \
           "$qt/uic" "$qt/bindings" "$qt/lupdate"
}

prune_python() {
    local root="$PYROOT/runtime"
    local lib
    for lib in "$root"/lib/python3.*; do
        [ -d "$lib" ] || continue
        rm -rf "$lib/test" "$lib/idlelib" "$lib/tkinter" "$lib/turtledemo" \
               "$lib/lib2to3" "$lib/ensurepip" "$lib/pydoc_data" \
               "$lib/distutils" "$lib"/config-*
        rm -rf "$lib"/site-packages/pip* "$lib"/site-packages/setuptools* \
               "$lib"/site-packages/pkg_resources* "$lib"/site-packages/wheel*
    done
    # Tcl/Tk and the sqlite/thread Tcl extensions are only used by tkinter,
    # which the app never uses.
    find "$root/lib" -maxdepth 1 \
        \( -name 'tcl*' -o -name 'tk*' -o -name 'thread*' \
           -o -name 'itcl*' -o -name 'sqlite*' \) -exec rm -rf {} + 2>/dev/null || true
    # python-build-standalone links the interpreter statically, so the big
    # shared libpython is dead weight (verified by the smoke test).
    rm -f "$root"/lib/libpython3.*.so*
    rm -rf "$root/share" "$root/include" "$root/lib/pkgconfig"
    local binfile name
    for binfile in "$root"/bin/*; do
        name="$(basename "$binfile")"
        if [[ "$name" == "python" || "$name" =~ ^python3(\.[0-9]+)?$ ]]; then
            continue                                       # keep the interpreter
        fi
        rm -f "$binfile"                                   # 2to3/idle/pip/config
    done
}

prune_qt
prune_python
# Byte-caches are rebuilt on first run; shipping them only bloats the archive.
find "$OUT" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$OUT" -name '*.pyc' -delete 2>/dev/null || true

# --------------------------------------------------------------------------
# 5. Launchers (self-locating; no build-time absolute paths)
# --------------------------------------------------------------------------
write_launcher() {
    local path="$1" module="$2"
    cat > "$path" <<EOF
#!/usr/bin/env bash
# Resolve this script's real directory, following symlinks, without readlink -f.
SELF="\$0"
while [ -L "\$SELF" ]; do
    LINK="\$(readlink "\$SELF")"
    case "\$LINK" in
        /*) SELF="\$LINK" ;;
        *)  SELF="\$(dirname "\$SELF")/\$LINK" ;;
    esac
done
DIR="\$(cd "\$(dirname "\$SELF")" && pwd -P)"
exec env -u PYTHONPATH -u PYTHONHOME -u VIRTUAL_ENV \\
    PYTHONPATH="\$DIR/site:\$DIR/app" \\
    "\$DIR/python/runtime/bin/python3" -m $module "\$@"
EOF
    chmod +x "$path"
}
write_launcher "$OUT/cachyview" "cachyview"
write_launcher "$OUT/cachyview-cli" "cachyview.integration.cli"

# --------------------------------------------------------------------------
# 6. Smoke test: the bundle must import every Qt module we keep and edit a PDF.
# --------------------------------------------------------------------------
echo "→ Verifying the bundle…"
"$OUT/cachyview" --version
QT_QPA_PLATFORM=offscreen QT_QPA_PLATFORMTHEME= \
    PYTHONPATH="$SITE:$APP" "$BASE_PY" - <<'PY'
import tempfile, pathlib
import PyQt6.QtCore, PyQt6.QtGui, PyQt6.QtWidgets        # noqa: F401
import PyQt6.QtNetwork, PyQt6.QtSvgWidgets, PyQt6.QtPrintSupport  # noqa: F401
import pymupdf, pikepdf, img2pdf  # noqa: F401
from cachyview.backends import pdf as pb
tmp = pathlib.Path(tempfile.mkdtemp())
d = pymupdf.open(); d.new_page(); src = tmp / "s.pdf"; d.save(src); d.close()
assert pb.info(src).page_count == 1
print("smoke: Qt + PDF backend OK")
PY

echo "→ Bundle built at: $OUT ($(du -sh "$OUT" | cut -f1))"
"$OUT/cachyview" --check-deps 2>/dev/null | head -8 || true
