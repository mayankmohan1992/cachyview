#!/usr/bin/env bash
# Install CachyView for the current user.  No root, no system files touched.
#
#   ./install.sh              install (or upgrade) and register with Dolphin
#   ./install.sh --uninstall  remove everything this script created
#
# Everything lives in two places:
#   ~/.local/share/cachyview          the app and its private virtualenv
#   ~/.local/share/applications, kio  the launcher and right-click actions
set -euo pipefail

APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/cachyview"
BIN_DIR="$HOME/.local/bin"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
info()  { printf '\033[36m%s\033[0m\n' "$*"; }

uninstall() {
    info "Removing CachyView…"
    if [[ -x "$APP_DIR/venv/bin/python" ]]; then
        "$APP_DIR/venv/bin/python" -m cachyview --uninstall-integration || true
    else
        rm -f "${XDG_DATA_HOME:-$HOME/.local/share}"/applications/cachyview.desktop
        rm -f "${XDG_DATA_HOME:-$HOME/.local/share}"/kio/servicemenus/cachyview-*.desktop
    fi
    rm -rf "$APP_DIR"
    rm -f "$BIN_DIR/cachyview" "$BIN_DIR/cachyview-cli"
    command -v update-desktop-database >/dev/null &&
        update-desktop-database "${XDG_DATA_HOME:-$HOME/.local/share}/applications" || true
    command -v kbuildsycoca6 >/dev/null && kbuildsycoca6 --noincremental >/dev/null 2>&1 || true
    green "CachyView removed."
    exit 0
}

[[ "${1:-}" == "--uninstall" ]] && uninstall

# --- required system packages ------------------------------------------------
missing=()
for pkg in python-pyqt6 python-pillow python-zstandard 7zip; do
    pacman -Q "$pkg" &>/dev/null || missing+=("$pkg")
done
if (( ${#missing[@]} )); then
    red "Missing required packages: ${missing[*]}"
    echo "Install them first:"
    echo "  paru -S --needed ${missing[*]}"
    exit 1
fi

# --- build the app venv -------------------------------------------------------
info "Installing CachyView to $APP_DIR"
rm -rf "$APP_DIR"
mkdir -p "$APP_DIR" "$BIN_DIR"
cp -r "$SRC_DIR/cachyview" "$SRC_DIR/pyproject.toml" "$APP_DIR/"
[[ -f "$SRC_DIR/README.md" ]] && cp "$SRC_DIR/README.md" "$APP_DIR/"

# --system-site-packages so the distro PyQt6/Pillow (built for this python) are used.
/usr/bin/python3 -m venv --system-site-packages "$APP_DIR/venv"
"$APP_DIR/venv/bin/python" -c "import PyQt6, PIL" || {
    red "The virtualenv cannot see PyQt6/Pillow."; exit 1; }

# Put the app on the venv's import path.  A .pth file is used rather than
# `pip install` so the install works offline and needs no build backend.
SITE_DIR="$("$APP_DIR/venv/bin/python" -c 'import sysconfig; print(sysconfig.get_path("purelib"))')"
echo "$APP_DIR" > "$SITE_DIR/cachyview.pth"
"$APP_DIR/venv/bin/python" -c "import cachyview" || {
    red "The app is not importable from its virtualenv."; exit 1; }

# --- launcher scripts ---------------------------------------------------------
# `env -u PYTHONPATH` matters: a PYTHONPATH inherited from another interpreter
# shadows compiled modules and breaks Pillow and every python-based helper.
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
chmod +x "$BIN_DIR/cachyview" "$BIN_DIR/cachyview-cli"

# --- desktop and Dolphin integration -------------------------------------------
"$APP_DIR/venv/bin/python" - <<EOF
from cachyview.integration.desktop import install
for path in install("$BIN_DIR/cachyview", "$BIN_DIR/cachyview-cli"):
    print(f"  {path}")
EOF

green "CachyView installed."
echo
"$BIN_DIR/cachyview" --check-deps || true
echo
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    red "Note: $BIN_DIR is not on your PATH."
    echo "  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.zshrc"
fi
echo "Run 'cachyview <file>' or right-click a file in Dolphin."
echo "Uninstall with: $SRC_DIR/install.sh --uninstall"
