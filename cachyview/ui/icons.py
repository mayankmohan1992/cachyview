"""Freedesktop theme icons with a text fallback if the theme has no match."""
from __future__ import annotations

from PyQt6.QtGui import QIcon, QKeySequence
from PyQt6.QtWidgets import QToolBar, QToolButton


def icon(*names: str) -> QIcon:
    for name in names:
        got = QIcon.fromTheme(name)
        if not got.isNull():
            return got
    return QIcon()


def add_action(bar: QToolBar, names: str | tuple[str, ...], text: str,
               slot, *, shortcut: str | QKeySequence | None = None,
               checkable: bool = False, tooltip: str | None = None):
    """Add a toolbar action. *names* is one theme id or a fallback list."""
    if isinstance(names, str):
        names = (names,)
    ic = icon(*names)
    if ic.isNull():
        act = bar.addAction(text, slot)
    else:
        act = bar.addAction(ic, text, slot)
    if act is None:
        return None
    if shortcut is not None:
        act.setShortcut(shortcut)
        tip = tooltip or text
        seq = shortcut if isinstance(shortcut, str) else shortcut.toString()
        act.setToolTip(f"{tip} ({seq})" if seq else tip)
    else:
        act.setToolTip(tooltip or text)
    act.setCheckable(checkable)
    return act


def style_bar(bar: QToolBar) -> None:
    from PyQt6.QtCore import QSize, Qt
    bar.setIconSize(QSize(22, 22))
    bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
    bar.setMovable(False)


def icon_button(parent, names: str | tuple[str, ...], text: str) -> QToolButton:
    if isinstance(names, str):
        names = (names,)
    btn = QToolButton(parent)
    ic = icon(*names)
    if ic.isNull():
        btn.setText(text)
    else:
        btn.setIcon(ic)
        btn.setToolTip(text)
    return btn
