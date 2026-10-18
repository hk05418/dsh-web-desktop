"""Server log viewer (ring-buffered, live-appending)."""
from __future__ import annotations

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QDialog, QLabel, QPlainTextEdit, QVBoxLayout

from ..server.manager import ServerManager


class LogWindow(QDialog):
    def __init__(self, server: ServerManager, parent: object | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("dsh web 服务器日志")
        self.resize(980, 520)
        self._view = QPlainTextEdit()
        self._view.setReadOnly(True)
        self._view.setMaximumBlockCount(5000)
        self._view.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self._header = QLabel("实时跟随（保留最近 5000 行，token 已打码）")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self._header)
        layout.addWidget(self._view)
        server.log_line.connect(self._append)
        for line in server.log_lines():
            self._view.appendPlainText(line)

    def _append(self, line: str) -> None:
        self._view.appendPlainText(line)
