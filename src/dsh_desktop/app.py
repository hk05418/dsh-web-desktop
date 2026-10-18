"""Application assembly: Qt app, single instance, server, probe, window, tray."""
from __future__ import annotations

import os
import sys
from urllib.parse import parse_qs, urlsplit

from PySide6.QtCore import QDir, QLockFile
from PySide6.QtWidgets import QApplication

from .config import Config
from .probe.worker import ProbeWorker
from .server.capture import ReadyInfo, parse_ready_line
from .server.manager import ServerManager
from .ui.main_window import MainWindow
from .ui.tray import TrayController

_app: QApplication | None = None
_lock: QLockFile | None = None


def quit_app() -> None:
    """Shared quit path (window and tray both funnel here)."""
    assert _app is not None
    _app.quit()


def _parse_attach(line: str) -> ReadyInfo | None:
    """Accept the printed `dsh web: ...` line or a plain URL carrying ?token=."""
    ready = parse_ready_line(line)
    if ready is not None:
        return ready
    stripped = line.strip()
    if "://" in stripped:
        parts = urlsplit(stripped)
        token = parse_qs(parts.query).get("token", [""])[0]
        if token:
            return ReadyInfo(base=f"{parts.scheme}://{parts.netloc}".rstrip("/"), token=token)
    return None


def _ensure_fcitx5_plugin() -> None:
    """Ensure the fcitx5 input-context plugin is present in this venv's Qt.

    Linux/X11 only: Qt6 drives fcitx5 through the platforminputcontexts plugin,
    which the PySide6 wheel from PyPI does NOT ship, so Chinese input silently
    fails (no candidate window). If the plugin is missing, copy it from the
    system Qt (requires matching major.minor version — the plugin is ABI-bound
    to Qt). Idempotent: a no-op once the plugin is present. On Windows/macOS the
    OS provides the IME, so this is a no-op.
    """
    import sys

    if sys.platform != "linux":
        return
    import shutil
    from pathlib import Path

    try:
        import PySide6

        qt_dir = Path(PySide6.__file__).parent / "Qt"
    except Exception:
        return
    plugin_dir = qt_dir / "plugins" / "platforminputcontexts"
    target = plugin_dir / "libfcitx5platforminputcontextplugin.so"
    if target.exists():
        return
    name = "libfcitx5platforminputcontextplugin.so"
    candidates = [
        Path(f"/usr/lib/qt6/plugins/platforminputcontexts/{name}"),
        Path(f"/usr/lib64/qt6/plugins/platforminputcontexts/{name}"),
        Path(f"/usr/lib/x86_64-linux-gnu/qt6/plugins/platforminputcontexts/{name}"),
    ]
    for src in candidates:
        if src.exists():
            try:
                plugin_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, target)
                print(f"[ime] copied fcitx5 input plugin from {src}", flush=True)
            except Exception as e:  # noqa: BLE001 - report and continue
                print(f"[ime] failed to copy fcitx5 plugin: {e}", flush=True)
            return
    print(
        "[ime] fcitx5 input plugin missing from venv and system Qt; "
        "Chinese input may not work on X11",
        flush=True,
    )


def main() -> int:
    global _app, _lock
    config = Config.load()
    if config.disable_gpu:
        # Deterministic CPU rendering: skip the Vulkan/GBM probe (which fails on
        # GPU-less machines) and force compositing onto the CPU. This avoids the
        # software-rendering fallback that can leave an initial region unpainted.
        os.environ.setdefault(
            "QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing"
        )
    # X11 Chinese input: ensure the fcitx5 platforminputcontexts plugin is
    # present in this venv's Qt (the PyPI wheel omits it). Must run before the
    # QApplication is constructed (plugins are discovered at platform init).
    _ensure_fcitx5_plugin()

    _app = QApplication(sys.argv)
    _app.setApplicationName("dsh-desktop")
    _app.setOrganizationName("dsh-desktop")

    _lock = QLockFile(QDir.tempPath() + "/dsh-desktop.lock")
    if not _lock.tryLock(100):
        print("dsh-desktop 已在运行")
        return 0

    server = ServerManager(config)
    probe = ProbeWorker(server.target)
    window = MainWindow(config, server, probe)
    tray = TrayController(config, server)
    # Console visibility when launched from a terminal (log window shows the
    # same lines; probe status is shown in the status bar, not printed).
    server.log_line.connect(lambda line: print(f"[log] {line}", flush=True))
    tray.show_window.connect(lambda: (window.show(), window.raise_(), window.activateWindow()))
    tray.start_server.connect(server.start)
    tray.stop_server.connect(server.stop)
    tray.open_log.connect(window.open_log)
    tray.quit_app.connect(window.request_quit)

    attach = _parse_attach(config.attach_line) if config.attach_line else None
    if attach is not None:
        server.log_line.emit("attach 模式：连接外部 dsh web 实例（不托管进程）")
        server.attach(attach)
    elif config.auto_start_server:
        server.start()

    # NOTE: the window is shown by MainWindow once the URL is known (load_ready)
    # or on server failure. Showing an empty webview first and loading the URL
    # ~10s later leaves a stale white region in the software-rendering compositor.
    probe.start()
    rc = _app.exec()
    probe.request_stop()
    probe.wait(3_000)
    server.shutdown()
    _lock.unlock()
    return rc
