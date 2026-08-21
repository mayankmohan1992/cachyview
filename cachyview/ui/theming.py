"""System theme integration and the shared shortcut reference.

CachyView does NOT force its own look.  On KDE (and other desktops) it adopts
the platform theme so colours, fonts and iconography match the user's shell.
Where Qt exposes a colour-scheme hint (Qt 6.5+) we read it so a dark session
gets a dark-appropriate palette without hard-coding colours.
"""
from __future__ import annotations

import os
from typing import Callable


def desktop_is_kde() -> bool:
    return "KDE" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper() \
        or "plasma" in os.environ.get("DESKTOP_SESSION", "").lower()


def apply_system_theme(app) -> str:
    """Adopt the desktop's native theme; return the style name chosen.

    We deliberately avoid forcing "Fusion" except as a fallback when no
    platform theme is in play (e.g. a bare Wayland/X11 session).  This keeps
    CachyView visually consistent with the rest of CachyOS/KDE.
    """
    from PyQt6.QtWidgets import QStyleFactory

    preferred = ["kvantum", "breeze", "oxygen", "gtk3", "adwaita", "fusion"]
    available = [s.lower() for s in QStyleFactory.keys()]
    chosen = ""
    for style in preferred:
        if style in available:
            chosen = style
            break
    if not chosen:
        chosen = app.style().objectName() if app.style() else "fusion"
    app.setStyle(chosen)

    # Honour an explicit dark request even when the platform theme is silent.
    scheme = os.environ.get("CACHYVIEW_COLOR_SCHEME", "").lower()
    if scheme in ("dark", "light"):
        _apply_color_scheme(app, scheme == "dark")
    elif hasattr(app, "styleHints"):
        hints = app.styleHints()
        if hasattr(hints, "colorScheme"):
            try:
                from PyQt6.QtCore import Qt
                scheme_val = hints.colorScheme()
                _apply_color_scheme(app, scheme_val == Qt.ColorScheme.Dark)
            except Exception:
                pass
    return chosen


def _apply_color_scheme(app, dark: bool) -> None:
    """Tint the palette for dark/light without fighting the platform theme."""
    from PyQt6.QtGui import QColor, QPalette
    from PyQt6.QtCore import Qt

    pal = QPalette()
    if dark:
        pal.setColor(QPalette.ColorRole.Window, QColor(35, 35, 40))
        pal.setColor(QPalette.ColorRole.WindowText, QColor(230, 230, 235))
        pal.setColor(QPalette.ColorRole.Base, QColor(28, 28, 33))
        pal.setColor(QPalette.ColorRole.AlternateBase, QColor(45, 45, 52))
        pal.setColor(QPalette.ColorRole.Text, QColor(230, 230, 235))
    else:
        pal.setColor(QPalette.ColorRole.Window, QColor(245, 245, 247))
        pal.setColor(QPalette.ColorRole.WindowText, QColor(30, 30, 35))
        pal.setColor(QPalette.ColorRole.Base, QColor(255, 255, 255))
        pal.setColor(QPalette.ColorRole.AlternateBase, QColor(240, 240, 245))
        pal.setColor(QPalette.ColorRole.Text, QColor(30, 30, 35))
    pal.setColor(QPalette.ColorRole.Button, pal.color(QPalette.ColorRole.Window))
    pal.setColor(QPalette.ColorRole.ButtonText,
                 pal.color(QPalette.ColorRole.WindowText))
    app.setPalette(pal)


# A single source of truth for the keyboard map, shown in Help -> Shortcuts.
SHORTCUTS: list[tuple[str, str, str]] = [
    ("Open files", "Ctrl+O", "Open one or more files"),
    ("Save", "Ctrl+S", "Save the current tab"),
    ("Close tab", "Ctrl+W", "Close the focused tab"),
    ("Quit", "Ctrl+Q", "Quit CachyView"),
    ("Undo edit", "Ctrl+Z", "Undo the last image/PDF edit"),
    ("Redo edit", "Ctrl+Shift+Z", "Redo an undone edit"),
    ("Batch processing", "Ctrl+B", "Open the batch queue"),
    ("Zoom in", "Ctrl++", "Zoom the current view in"),
    ("Zoom out", "Ctrl+-", "Zoom the current view out"),
    ("Fit to window", "Ctrl+0", "Fit the view to the window"),
    ("Next page", "Right / PgDn", "Go to the next PDF page"),
    ("Previous page", "Left / PgUp", "Go to the previous PDF page"),
    ("Toggle annotation", "A", "Enter/exit PDF annotation mode"),
    ("Toggle picker", "P", "Image colour picker (toggle)"),
    ("Toggle ruler", "R", "Image ruler (toggle)"),
    ("Toggle magnifier", "M", "Image magnifier (toggle)"),
    ("Show shortcuts", "?", "Show this list"),
    ("Command palette", "Ctrl+K", "Fuzzy-run any action"),
    ("Inspector", "Ctrl+Shift+I", "Toggle the file info sidebar"),
    ("Find", "Ctrl+F", "Find in the current document"),
]


def format_shortcuts() -> str:
    rows = "\n".join(f"  {keys:<14} {name}" for name, keys, _ in SHORTCUTS)
    return "CachyView keyboard shortcuts\n\n" + rows


def bind_shortcuts(window, handlers: dict[str, Callable[[], None]]) -> None:
    """Wire the SHORTCUTS table to handlers by name (no-ops if missing)."""
    from PyQt6.QtGui import QKeySequence, QShortcut

    keymap = {name: keys for name, keys, _ in SHORTCUTS}
    for name, fn in handlers.items():
        keys = keymap.get(name)
        if not keys:
            continue
        for combo in keys.split(" / "):
            sc = QShortcut(QKeySequence(combo), window)
            sc.activated.connect(fn)
