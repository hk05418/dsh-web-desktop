"""System tray: server state dot, show/hide, server actions, quit."""
from __future__ import annotations

import os

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from ..config import Config, find_app_icon
from ..server.manager import ServerManager, ServerState

_STATE_COLORS = {
    ServerState.STOPPED: "#8a8f98",
    ServerState.STARTING: "#e6a23c",
    ServerState.READY: "#67c23a",
    ServerState.CRASHED: "#f56c6c",
    ServerState.FAILED: "#f56c6c",
}
_STATE_TEXT = {
    ServerState.STOPPED: "服务器已停止",
    ServerState.STARTING: "服务器启动中…",
    ServerState.READY: "服务器运行中",
    ServerState.CRASHED: "服务器崩溃（等待自动重启）",
    ServerState.FAILED: "服务器启动失败",
}


def _dot_icon(color: str, base: QPixmap | None = None) -> QIcon:
    """Tray icon: optional base (whale logo) + a status dot in the corner."""
    size = 22
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if base is not None and not base.isNull():
        painter.drawPixmap(0, 0, size, size, base)
    # Status dot (bottom-right), with a white border for visibility on any base.
    dot = 9
    x = size - dot - 1
    y = size - dot - 1
    painter.setPen(QColor("white"))
    painter.setBrush(QColor(color))
    painter.drawEllipse(x, y, dot, dot)
    painter.end()
    return QIcon(pixmap)


class TrayController(QObject):
    """Owns the QSystemTrayIcon; window/server actions are wired by the caller."""

    show_window = Signal()
    stop_server = Signal()
    start_server = Signal()
    open_log = Signal()
    quit_app = Signal()

    def __init__(self, config: Config, server: ServerManager,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._tray = QSystemTrayIcon(self)
        self._tray.setToolTip("dsh-desktop")
        # Base icon (whale logo) for the tray; None falls back to a plain dot.
        self._base: QPixmap | None = None
        icon_path = find_app_icon()
        if icon_path is not None:
            self._base = QPixmap(str(icon_path))
        self._menu = QMenu()
        # NOTE: pass a callable (not a Signal) to addAction — PySide6 6.12 rejects
        # a Signal as the slot ("native Qt signal instance is not callable").
        # Use explicit .triggered.connect() instead.
        self._act_show = self._menu.addAction("显示窗口")
        self._act_show.triggered.connect(self.show_window)
        self._menu.addSeparator()
        self._act_start = self._menu.addAction("启动服务器")
        self._act_start.triggered.connect(self.start_server)
        self._act_stop = self._menu.addAction("停止服务器")
        self._act_stop.triggered.connect(self.stop_server)
        self._act_log = self._menu.addAction("服务器日志")
        self._act_log.triggered.connect(self.open_log)
        self._menu.addSeparator()
        self._act_quit = self._menu.addAction("退出")
        self._act_quit.triggered.connect(self.quit_app)
        # Platform-aware context menu:
        # - Windows: setContextMenu() works (the native tray menu triggers Qt actions).
        # - Linux (this CWM tray): the native context menu is rendered by the system
        #   but does NOT trigger Qt actions (clicking does nothing). So we handle
        #   Context activation and show a Qt menu at the cursor instead.
        import sys

        self._use_native_menu = os.name == "nt"
        if self._use_native_menu:
            self._tray.setContextMenu(self._menu)
        self._tray.activated.connect(self._on_activated)
        server.state_changed.connect(self._on_state)
        self._on_state(server.state)
        self._tray.show()

    def _on_state(self, state: str) -> None:
        color = _STATE_COLORS.get(state, "#8a8f98")
        self._tray.setIcon(_dot_icon(color, self._base))
        self._tray.setToolTip(f"dsh-desktop — {_STATE_TEXT.get(state, state)}")
        running = state in (ServerState.READY, ServerState.STARTING)
        self._act_start.setEnabled(not running)
        self._act_stop.setEnabled(running or state in (ServerState.CRASHED, ServerState.FAILED))

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_window.emit()
        elif reason == QSystemTrayIcon.ActivationReason.Context and not self._use_native_menu:
            # Non-native platform: show the Qt menu at the cursor (the system
            # tray's native menu doesn't fire Qt actions here).
            self._menu.exec_(QCursor.pos())
