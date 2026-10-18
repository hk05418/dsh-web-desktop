"""White-block diagnostic: reproduce with toggleable features.

Usage:
    python scripts/diag_whiteblock.py --features menu,status,page,probe,tray,zoom

Starts a dsh web server, opens a QtWebEngine window with the requested
features, prints "LOADED" once the page finishes loading, then stays open
so the outer harness can capture the screen frame.

Feature flags (comma separated):
    menu    add a QMenuBar (服务器/视图/帮助)
    status  add a QStatusBar
    page    use DshWebPage (acceptNavigationRequest/createWindow overrides)
    probe   start a background QThread (like ProbeWorker)
    tray    create a QSystemTrayIcon
    zoom    call setZoomFactor(1.0)
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import threading

REPO = "/home/ruby/deepseek-harness"
READY_RE = re.compile(r"^dsh web: (https?://\S+?)/\?token=([A-Za-z0-9._~+-]+)\s*$")


def start_server() -> str:
    proc = subprocess.Popen(
        ["pnpm", "dsh", "web", "--no-open", "--port", "0"],
        cwd=REPO,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    for line in proc.stdout:
        m = READY_RE.match(line.strip())
        if m:
            return m.group(1) + "/?token=" + m.group(2)
    raise RuntimeError("server did not become ready")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", default="")
    args = parser.parse_args()
    features = {f for f in args.features.split(",") if f}
    print(f"[diag] features={sorted(features)}", flush=True)

    url = start_server()
    print("[diag] server ready", flush=True)

    from PySide6.QtCore import QThread, QUrl
    from PySide6.QtWidgets import (
        QApplication,
        QLabel,
        QMainWindow,
        QSystemTrayIcon,
    )
    from PySide6.QtWebEngineCore import QWebEngineProfile
    from PySide6.QtWebEngineWidgets import QWebEngineView

    app = QApplication(sys.argv)
    app.setApplicationName("diag-whiteblock")

    win = QMainWindow()
    view = QWebEngineView()
    if "page" in features:
        from dsh_desktop.ui.web_page import DshWebPage

        view.setPage(DshWebPage(QWebEngineProfile.defaultProfile(), win))
    if "zoom" in features:
        view.setZoomFactor(1.0)
    view.setUrl(QUrl(url))
    win.setCentralWidget(view)

    if "menu" in features:
        mb = win.menuBar()
        mb.addMenu("服务器(&S)")
        mb.addMenu("视图(&V)")
        mb.addMenu("帮助(&H)")
    if "status" in features:
        sb = win.statusBar()
        sb.addWidget(QLabel("服务器 test"))
        sb.addPermanentWidget(QLabel("探针"))

    if "tray" in features:
        tray = QSystemTrayIcon(win)
        from PySide6.QtGui import QIcon

        tray.setIcon(QIcon.fromTheme("application-x-executable"))
        tray.show()

    if "probe" in features:

        class IdleThread(QThread):
            def run(self) -> None:  # noqa: D102 - mimic a worker thread
                import time

                while True:
                    time.sleep(1)

        _probe = IdleThread()
        _probe.start()

    if "devtools" in features:
        # Replicate the full app's hidden second QWebEngineView (DevTools page).
        dev2 = QWebEngineView(win)
        dev2.setPage(view.page().devToolsPage())
        dev2.setWindowTitle("DevTools")
        dev2.resize(900, 600)
        _dev2 = dev2  # keep a reference

    if "dev2plain" in features:
        # A second hidden QWebEngineView with a plain page (no devTools).
        dev2 = QWebEngineView(win)
        dev2.setWindowTitle("Dev2")
        dev2.resize(900, 600)
        _dev2b = dev2  # keep a reference

    win.resize(1440, 900)
    win.setWindowTitle("DIAG WHITEBLOCK")
    win.show()
    print("[diag] window shown", flush=True)

    state = {"loaded": False}

    def on_loaded(ok: bool) -> None:
        state["loaded"] = True
        print(f"[diag] LOADED ok={ok}", flush=True)

    view.page().loadFinished.connect(on_loaded)
    app.exec()


if __name__ == "__main__":
    main()
