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


def _active_fcitx5_base() -> "Path | None":
    """The plugin-base dir Qt actually searches (contains ``platforminputcontexts/``).

    - Nuitka standalone: ``<PySide6>/qt-plugins`` — Nuitka's pyside6 plugin sets
      QCoreApplication library paths to exactly this dir, so the fcitx5 plugin
      must live here to be found at runtime. Detected by the dir's presence.
    - venv (from source): ``<PySide6>/Qt/plugins``.
    """
    from pathlib import Path

    try:
        import PySide6

        p = Path(PySide6.__file__).resolve().parent
    except Exception:
        return None
    nuitka_base = p / "qt-plugins"
    if nuitka_base.is_dir():
        return nuitka_base
    return p / "Qt" / "plugins"


def _ensure_fcitx5_plugin() -> None:
    """Ensure the fcitx5 input-context plugin is present in this app's Qt.

    Linux/X11 only: Qt6 drives fcitx5 through the platforminputcontexts plugin,
    which the PySide6 wheel from PyPI does NOT ship, so Chinese input silently
    fails (no candidate window). If the plugin is missing from the app's Qt
    (venv or frozen bundle), copy it from the system Qt (requires matching
    major.minor version — the plugin is ABI-bound to Qt). Idempotent: a no-op
    once present. On Windows/macOS the OS provides the IME, so this is a no-op.
    """
    if sys.platform != "linux":
        return
    import shutil
    from pathlib import Path

    name = "libfcitx5platforminputcontextplugin.so"
    base = _active_fcitx5_base()
    if base is None:
        return
    target_dir = base / "platforminputcontexts"
    if (target_dir / name).exists():
        return  # already present in the dir Qt searches
    src = next(
        (
            Path(p)
            for p in (
                f"/usr/lib/qt6/plugins/platforminputcontexts/{name}",
                f"/usr/lib64/qt6/plugins/platforminputcontexts/{name}",
                f"/usr/lib/x86_64-linux-gnu/qt6/plugins/platforminputcontexts/{name}",
            )
            if Path(p).exists()
        ),
        None,
    )
    if src is None:
        print(
            "[ime] fcitx5 input plugin missing from app and system Qt; "
            "Chinese input may not work on X11",
            flush=True,
        )
        return
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target_dir / name)
        print(f"[ime] copied fcitx5 input plugin from {src} to {target_dir}", flush=True)
    except OSError as e:  # noqa: BLE001 - report
        print(f"[ime] failed to copy fcitx5 plugin to {target_dir}: {e}", flush=True)


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
