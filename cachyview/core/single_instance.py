"""Single-instance hand-off via a local socket.

A second `cachyview file` launch sends the paths to the first process and
exits, so Dolphin 'Open with' does not spawn a stack of windows.
"""
from __future__ import annotations

import os
from collections.abc import Callable

from PyQt6.QtCore import QByteArray, QObject, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

SOCKET = f"cachyview-{os.getuid()}"


class InstanceServer(QObject):
    """Listen for paths from later launches."""

    paths_received = pyqtSignal(list)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._accept)

    def listen(self) -> bool:
        QLocalServer.removeServer(SOCKET)
        return self._server.listen(SOCKET)

    def _accept(self) -> None:
        sock = self._server.nextPendingConnection()
        if sock is None:
            return
        sock.readyRead.connect(lambda s=sock: self._read(s))

    def _read(self, sock: QLocalSocket) -> None:
        data = bytes(sock.readAll()).decode("utf-8", "replace")
        sock.disconnectFromServer()
        lines = [ln for ln in data.split("\n") if ln.strip()]
        if lines[:1] == ["CACHYVIEW"]:
            lines = lines[1:]
        if lines[:1] == ["open"]:
            lines = lines[1:]
        if lines:
            self.paths_received.emit(lines)


def try_handoff(paths: list[str]) -> bool:
    """If another instance is alive, send *paths* to it and return True."""
    sock = QLocalSocket()
    sock.connectToServer(SOCKET)
    if not sock.waitForConnected(400):
        return False
    payload = "CACHYVIEW\nopen\n" + "\n".join(paths) + "\n"
    sock.write(QByteArray(payload.encode("utf-8")))
    sock.flush()
    sock.waitForBytesWritten(400)
    sock.disconnectFromServer()
    return True


def bind_handoff(callback: Callable[[list[str]], None]) -> InstanceServer | None:
    server = InstanceServer()
    if not server.listen():
        return None
    server.paths_received.connect(callback)
    return server
