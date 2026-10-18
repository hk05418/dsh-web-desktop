#!/usr/bin/env python3
"""M0 smoke test: load the real dsh web UI in a QtWebEngine (Chromium) window.

Spawns ``pnpm dsh web --no-open --port <port>`` (random port by default so it
never clashes with your running 3080 instance), waits for the token line,
then opens the UI in a separate QtWebEngine window. Same DSH_HOME => your
sessions and account are visible. Close the window (or Ctrl+C here) to stop
the smoke server.

Usage:
    uv run python scripts/smoke_webview.py [--port 0] [--repo ~/deepseek-harness]
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

READY_RE = re.compile(r"^dsh web: (https?://\S+?)/\?token=([A-Za-z0-9._~+-]+)\s*$")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default=str(Path.home() / "deepseek-harness"))
    ap.add_argument("--port", type=int, default=0, help="0 = OS picks a free port")
    ap.add_argument("--ready-timeout", type=float, default=90.0)
    args = ap.parse_args()

    ready: dict[str, str] = {"base": "", "token": ""}
    proc = subprocess.Popen(
        [shutil.which("pnpm") or "pnpm", "dsh", "web", "--no-open", "--port", str(args.port)],
        cwd=args.repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    def pump() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            shown = re.sub(r"(token=)\S+", r"\1***", line.rstrip())
            print(f"[server] {shown}", flush=True)
            m = READY_RE.match(line)
            if m and not ready["base"]:
                ready["base"], ready["token"] = m.group(1), m.group(2)

    threading.Thread(target=pump, daemon=True).start()

    deadline = time.monotonic() + args.ready_timeout
    while time.monotonic() < deadline:
        if ready["base"]:
            break
        if proc.poll() is not None:
            print("[smoke] ERROR: server exited before becoming ready", file=sys.stderr)
            return 1
        time.sleep(0.1)
    if not ready["base"]:
        print("[smoke] ERROR: timed out waiting for the `dsh web: ...` line", file=sys.stderr)
        proc.kill()
        return 1

    url = f"{ready['base']}/?token={ready['token']}"
    print(f"[smoke] server ready at {ready['base']} (token=***)", flush=True)
    print(f"[smoke] opening QtWebEngine window…", flush=True)

    from PySide6.QtCore import QUrl
    from PySide6.QtWidgets import QApplication, QMainWindow
    from PySide6.QtWebEngineWidgets import QWebEngineView

    app = QApplication(sys.argv)
    view = QWebEngineView()
    page = view.page()
    page.loadFinished.connect(lambda ok: print(f"[smoke] loadFinished ok={ok}", flush=True))
    page.titleChanged.connect(lambda t: print(f"[smoke] title={t}", flush=True))
    view.setUrl(QUrl(url))

    win = QMainWindow()
    win.setCentralWidget(view)
    win.resize(1400, 900)
    win.setWindowTitle("dsh-desktop M0 smoke — dsh web in QtWebEngine")
    win.show()
    print("[smoke] window shown. Try: 新建会话 → 发消息 → 看流式输出 → 审批/文件侧栏", flush=True)

    rc = app.exec()
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    print(f"[smoke] done, rc={rc}", flush=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
