"""Main window: embedded web UI + status bar + menus."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QLabel,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView

from ..config import Config, find_app_icon
from ..probe.worker import ProbeWorker
from ..server.capture import ReadyInfo
from ..server.manager import ServerManager, ServerState
from .log_window import LogWindow
from .web_page import DshWebPage

_DOT_COLORS = {
    ServerState.STOPPED: "#8a8f98",
    ServerState.STARTING: "#e6a23c",
    ServerState.READY: "#67c23a",
    ServerState.CRASHED: "#f56c6c",
    ServerState.FAILED: "#f56c6c",
}
_PROBE_TEXT = {
    "down": "服务器未就绪",
    "auth": "探针认证中…",
    "ok": "{n} 个会话",
    "error": "状态探针异常",
}


class MainWindow(QMainWindow):
    def __init__(self, config: Config, server: ServerManager, probe: ProbeWorker) -> None:
        super().__init__()
        self._config = config
        self._server = server
        self._probe = probe
        self._confirm_hide_shown = False
        self._log_window: LogWindow | None = None

        self.setWindowTitle("DeepSeek Harness")
        icon_path = find_app_icon()
        if icon_path is not None:
            self.setWindowIcon(QIcon(str(icon_path)))
        self.resize(1440, 900)

        self._view = QWebEngineView(self)
        self._view.setPage(DshWebPage(QWebEngineProfile.defaultProfile(), self))
        self._view.setZoomFactor(config.zoom)
        self._view.page().loadFinished.connect(self._on_load_finished)

        # Stacked central widget: page 0 = webview, page 1 = restart placeholder.
        # QWebEngineView is a native surface, so a Qt widget cannot be layered on
        # top of it; switching pages is the reliable way to show a "重启中…" mask.
        self._stack = QStackedWidget(self)
        self._stack.addWidget(self._view)  # index 0
        self._placeholder = self._build_placeholder()
        self._stack.addWidget(self._placeholder)  # index 1
        self.setCentralWidget(self._stack)

        self._build_status_bar()
        self._build_menu()

        server.state_changed.connect(self._on_server_state)
        server.ready.connect(self.load_ready)
        server.failure.connect(self._on_server_failure)
        probe.status.connect(self._on_probe_status)
        self._on_server_state(server.state)

    # -- content ---------------------------------------------------------------
    def load_ready(self, ready: ReadyInfo) -> None:
        """Load the token-authenticated URL of a ready server."""
        self._view.setUrl(QUrl(ready.url))
        self._port_label.setText(f"服务器 {ready.base}")
        # Show only once the URL is set: showing an empty webview first and
        # loading later leaves a stale white region in the software compositor.
        if not self.isVisible():
            self.show()

    def _on_load_finished(self, ok: bool) -> None:
        self._server.log_line.emit(f"[webview] loadFinished ok={ok}")

    def force_repaint(self) -> None:
        """Force QtWebEngine to fully re-composite the viewport.

        A manual escape hatch (视图 → 强制重绘) for any rendering glitch:
        nudging the window size forces a full viewport re-alloc + re-composite,
        which is more reliable than a zoom change under software rendering.
        """
        geo = self.geometry()
        self.resize(geo.width() + 4, geo.height() + 4)
        QTimer.singleShot(60, lambda: self.resize(geo.width(), geo.height()))
        # Also jiggle the zoom as a secondary trigger.
        factor = self._view.zoomFactor()
        self._view.setZoomFactor(min(2.0, factor + 0.02))
        QTimer.singleShot(120, lambda: self._view.setZoomFactor(factor))

    # -- chrome -----------------------------------------------------------------
    def _build_status_bar(self) -> None:
        bar: QStatusBar = self.statusBar()
        self._dot = QLabel("●")
        self._dot.setStyleSheet("color: #8a8f98; font-size: 14px;")
        self._port_label = QLabel("服务器未启动")
        self._zoom_label = QLabel("")
        self._probe_label = QLabel("")
        bar.addWidget(self._dot)
        bar.addWidget(self._port_label)
        bar.addPermanentWidget(self._zoom_label)
        bar.addPermanentWidget(self._probe_label)
        self._update_zoom_label()

    def _build_placeholder(self) -> QWidget:
        """Restart mask: a centered '服务器重启中…' label on a dark background."""
        w = QWidget()
        w.setStyleSheet("background-color: #1e1e1e;")
        layout = QVBoxLayout(w)
        label = QLabel("服务器重启中…\n请稍候")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("color: #e6a23c; font-size: 20px;")
        layout.addWidget(label)
        return w

    def _build_menu(self) -> None:
        menubar = self.menuBar()

        m_server = menubar.addMenu("服务器(&S)")
        self._act_start = QAction("启动(&T)", self)
        self._act_start.triggered.connect(self._server.start)
        self._act_stop = QAction("停止(&P)", self)
        self._act_stop.triggered.connect(self._server.stop)
        self._act_restart = QAction("重启(&R)", self)
        self._act_restart.triggered.connect(self._server.restart)
        self._act_log = QAction("服务器日志(&L)…", self)
        self._act_log.triggered.connect(self._open_log)
        act_webcfg = QAction("打开 dsh-web 配置文件(&W)…", self)
        act_webcfg.triggered.connect(self._open_web_config)
        act_repodir = QAction("设置 DSH 目录(&D)…", self)
        act_repodir.triggered.connect(self._set_repo_dir)
        for action in (self._act_start, self._act_stop, self._act_restart, self._act_log, act_webcfg, act_repodir):
            m_server.addAction(action)

        m_view = menubar.addMenu("视图(&V)")
        # NOTE: PySide6 QAction has NO (text, parent, slot) constructor — the slot
        # is silently dropped. Always use explicit .triggered.connect().
        # (No back/forward: the dsh web UI is a single-page app — switching
        # sessions doesn't change the URL, so there's no navigation history.)
        act_reload = QAction("重新加载(&O)", self)
        act_reload.setShortcut("Ctrl+R")
        act_reload.triggered.connect(self._view.reload)
        m_view.addAction(act_reload)
        act_repaint = QAction("强制重绘(&R)（白屏时）", self)
        act_repaint.triggered.connect(self.force_repaint)
        m_view.addAction(act_repaint)
        m_view.addSeparator()
        act_fullscreen = QAction("全屏(&U)", self)
        act_fullscreen.setCheckable(True)
        act_fullscreen.setShortcut("F11")
        act_fullscreen.triggered.connect(self._toggle_fullscreen)
        m_view.addAction(act_fullscreen)
        m_view.addSeparator()
        act_zoom_in = QAction("放大(&I)", self)
        act_zoom_in.setShortcut("Ctrl+=")
        act_zoom_in.triggered.connect(lambda: self._zoom(0.1))
        act_zoom_out = QAction("缩小(&O)", self)
        act_zoom_out.setShortcut("Ctrl+-")
        act_zoom_out.triggered.connect(lambda: self._zoom(-0.1))
        act_zoom_reset = QAction("重置缩放(&Z)", self)
        act_zoom_reset.triggered.connect(lambda: self._set_zoom(1.0))
        for action in (act_zoom_in, act_zoom_out, act_zoom_reset):
            m_view.addAction(action)

        m_help = menubar.addMenu("帮助(&H)")
        act_shortcuts = QAction("快捷键(&K)", self)
        act_shortcuts.triggered.connect(self._show_shortcuts)
        m_help.addAction(act_shortcuts)
        act_config = QAction("打开配置文件(&C)…", self)
        act_config.triggered.connect(self._open_config)
        m_help.addAction(act_config)
        m_help.addSeparator()
        act_about = QAction("关于(&A)", self)
        act_about.triggered.connect(self._show_about)
        m_help.addAction(act_about)

        self._server_actions = (self._act_start, self._act_stop, self._act_restart)

    def _zoom(self, delta: float) -> None:
        self._set_zoom(self._view.zoomFactor() + delta)

    def _set_zoom(self, factor: float) -> None:
        self._view.setZoomFactor(max(0.5, min(2.0, factor)))
        self._update_zoom_label()

    def _update_zoom_label(self) -> None:
        if hasattr(self, "_zoom_label"):
            self._zoom_label.setText(f"{round(self._view.zoomFactor() * 100)}%")

    def _toggle_fullscreen(self, checked: bool) -> None:
        if checked:
            self.showFullScreen()
        else:
            self.showNormal()

    def _show_shortcuts(self) -> None:
        QMessageBox.information(
            self,
            "快捷键",
            "Ctrl+R    重新加载\n"
            "Ctrl+=    放大\n"
            "Ctrl+-    缩小\n"
            "F11       全屏",
        )

    def _open_in_editor(self, path: Path) -> None:
        """Open a file in the configured editor, or the system default.

        If ``config.editor`` is set, launch it directly via QProcess (avoids the
        system "Open With…" dialog when no default app is associated with the
        file type). Otherwise fall back to QDesktopServices.openUrl.
        """
        editor = self._config.editor.strip()
        if editor:
            from PySide6.QtCore import QProcess

            QProcess.startDetached(editor, [str(path)])
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _open_config(self) -> None:
        from pathlib import Path

        path = Path.home() / ".config" / "dsh_desktop" / "config.json"
        if not path.exists():
            QMessageBox.information(
                self,
                "配置文件",
                f"配置文件尚不存在（使用默认值）：\n{path}\n\n"
                "修改 port / disable_gpu / attach_line / editor 等后保存即可生效（重启应用）。",
            )
            return
        self._open_in_editor(path)

    def _open_web_config(self) -> None:
        """Open the dsh-web profile config (~/.dsh/profiles/web/cordis.patch.yml)."""
        from pathlib import Path

        path = Path.home() / ".dsh" / "profiles" / "web" / "cordis.patch.yml"
        if not path.exists():
            QMessageBox.information(
                self,
                "dsh-web 配置文件",
                f"配置文件尚不存在：\n{path}\n\n"
                "这是 dsh web 实例的 profile 配置（模型/提供方等）。",
            )
            return
        self._open_in_editor(path)

    def _set_repo_dir(self) -> None:
        """Pick the deepseek-harness checkout dir; update config + restart server.

        The server process uses repo_dir as its cwd, so a change requires a
        server restart to take effect.
        """
        from pathlib import Path

        from PySide6.QtWidgets import QFileDialog

        from ..config import is_valid_dsh_repo

        initial = str(Path(self._config.repo_dir)) if Path(self._config.repo_dir).exists() else str(Path.home())
        while True:
            path = QFileDialog.getExistingDirectory(
                self, "选择 deepseek-harness 检出目录", initial
            )
            if not path:
                return  # cancelled
            if is_valid_dsh_repo(path):
                break
            if QMessageBox.question(
                self,
                "目录无效",
                f"所选目录不是有效的 deepseek-harness 检出（缺少 apps/cli/src/bin.ts）：\n{path}\n\n"
                "仍要使用它吗？（服务器可能无法启动）",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            ) != QMessageBox.StandardButton.Yes:
                continue
            break  # user insists on using the invalid dir

        if path == self._config.repo_dir:
            return  # unchanged
        self._config.repo_dir = path
        self._config.save()
        self._server.log_line.emit(f"repo_dir 更新为 {path}（重启服务器生效）")
        # Restart the server so the new cwd takes effect (if it's running).
        if self._server.state in (ServerState.READY, ServerState.STARTING):
            self._server.restart()
        QMessageBox.information(
            self,
            "DSH 目录已更新",
            f"repo_dir 已设为：\n{path}\n\n"
            + ("服务器已重启以应用新目录。" if self._server.state == ServerState.STARTING else "下次启动服务器时生效。"),
        )

    def open_log(self) -> None:
        """Public log-window entry point (tray menu)."""
        self._open_log()

    def request_quit(self) -> None:
        """Tray quit: make sure the window is visible, then run the quit flow."""
        if not self.isVisible():
            self.show()
        self._really_quit()

    def _open_log(self) -> None:
        if self._log_window is None:
            self._log_window = LogWindow(self._server, self)
        self._log_window.show()
        self._log_window.raise_()
        self._log_window.activateWindow()

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "关于 dsh-desktop",
            "dsh-desktop 0.1.0\n\n"
            "PySide6 桌面管理端：托管 dsh web 服务器进程，\n"
            "内嵌完整 DeepSeek Harness Web GUI。\n",
        )

    # -- state hooks ---------------------------------------------------------------
    def _on_server_state(self, state: str) -> None:
        self._dot.setStyleSheet(f"color: {_DOT_COLORS.get(state, '#8a8f98')}; font-size: 14px;")
        running = state in (ServerState.READY, ServerState.STARTING)
        self._act_start.setEnabled(not running)
        self._act_stop.setEnabled(running or state in (ServerState.CRASHED, ServerState.FAILED))
        self._act_restart.setEnabled(running)
        # Restart mask: show the placeholder while (re)starting if the window is
        # already visible (a restart, not the initial start); back to the webview
        # once ready. The initial start keeps the webview (window is hidden until
        # load_ready, so no flicker).
        if state == ServerState.STARTING and self.isVisible():
            self._stack.setCurrentIndex(1)
        elif state == ServerState.READY:
            self._stack.setCurrentIndex(0)

    def _on_server_failure(self, reason: str) -> None:
        if not self.isVisible():
            self.show()
        QMessageBox.critical(self, "dsh web 服务器", reason)

    def _on_probe_status(self, phase: str, total: int, running: int, message: str) -> None:
        if phase == "ok":
            text = f"{total} 个会话" + (f" · {running} 运行中" if running else "")
        else:
            text = _PROBE_TEXT.get(phase, phase)
            text = text.format(n=total) if "{n}" in text else text
        self._probe_label.setText(text)
        self._probe_label.setToolTip(message)

    # -- window lifecycle ---------------------------------------------------------
    def closeEvent(self, event) -> None:  # noqa: N802 - Qt signature
        if not self._config.hide_to_tray:
            self._really_quit()
            event.accept()
            return
        if not self._confirm_hide_shown:
            self._confirm_hide_shown = True
            event.ignore()
            answer = QMessageBox.question(
                self,
                "dsh-desktop",
                "关闭窗口时最小化到系统托盘？\n（正在运行的任务不会中断）\n\n"
                "是 = 隐藏到托盘    否 = 退出应用",
            )
            if answer == QMessageBox.StandardButton.Yes:
                self.hide()
            else:
                self._really_quit()
                event.accept()
        else:
            self.hide()
            event.ignore()

    def _really_quit(self) -> None:
        if self._server.state in (ServerState.READY, ServerState.STARTING, ServerState.CRASHED):
            answer = QMessageBox.question(
                self,
                "退出 dsh-desktop",
                "服务器仍在运行，退出将停止 dsh web。\n"
                "正在运行的任务将会中断，确定退出？",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        from ..app import quit_app  # local import: app owns the QApplication

        quit_app()
