"""Owns the `dsh web` server process: start/stop/restart, ready capture, logs."""
from __future__ import annotations

import os
import socket
from collections import deque

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

from ..config import Config
from .capture import ReadyInfo, mask_tokens, parse_ready_line

STARTUP_TIMEOUT_MS = 60_000
STOP_GRACE_MS = 5_000
MAX_BACKOFF_MS = 30_000
LOG_LINES = 5_000


class ServerState:
    STOPPED = "stopped"
    STARTING = "starting"
    READY = "ready"
    CRASHED = "crashed"
    FAILED = "failed"


class ServerManager(QObject):
    """Runs `pnpm dsh web` (or attaches to an external instance) as a child process."""

    state_changed = Signal(str)
    ready = Signal(object)  # ReadyInfo
    log_line = Signal(str)  # token-masked stdout line
    failure = Signal(str)  # human-readable fatal reason (port busy / startup failure / crash)

    def __init__(self, config: Config, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._state = ServerState.STOPPED
        self._intentional_stop = False
        self._pending_restart = False
        self._ready_seen = False
        self._backoff_ms = 0
        self._line_buffer = ""
        self._ready_info: ReadyInfo | None = None
        self._lines: deque[str] = deque(maxlen=LOG_LINES)
        self._proc = QProcess(self)
        self._proc.readyReadStandardOutput.connect(self._pump_stdout)
        self._proc.finished.connect(self._on_finished)
        self._proc.errorOccurred.connect(self._on_error)
        # Cancellable stop-grace timer. A one-shot QTimer.singleShot here would be
        # a bug: after a fast restart the pending timer fires 5s later and kills
        # the NEW process. start() stops this timer before launching a new one.
        self._stop_timer = QTimer(self)
        self._stop_timer.setSingleShot(True)
        self._stop_timer.timeout.connect(self._enforce_stop)

    # -- state ---------------------------------------------------------------
    @property
    def state(self) -> str:
        return self._state

    @property
    def ready_info(self) -> ReadyInfo | None:
        return self._ready_info

    def log_lines(self) -> list[str]:
        return list(self._lines)

    def _set_state(self, state: str) -> None:
        if state != self._state:
            self._state = state
            self.state_changed.emit(state)

    # -- lifecycle ------------------------------------------------------------
    def start(self) -> None:
        if self._state in (ServerState.READY, ServerState.STARTING):
            return
        port = self._config.port
        if port and not self._port_free(port):
            self._set_state(ServerState.FAILED)
            self.failure.emit(
                f"端口 {port} 已被占用：先停掉终端里的 dsh web 让桌面端接管，"
                "或在设置里把 port 改为 0（随机端口）"
            )
            return
        self._intentional_stop = False
        self._pending_restart = False
        self._ready_seen = False
        self._line_buffer = ""
        # Cancel any pending stop-grace kill from a previous stop/restart so it
        # cannot kill the new process we are about to launch.
        self._stop_timer.stop()
        self._set_state(ServerState.STARTING)
        self._emit_log(f"$ {' '.join(self._command())}   (cwd={self._config.repo_dir})")
        self._proc.setWorkingDirectory(self._config.repo_dir)
        self._proc.setProcessChannelMode(QProcess.ProcessChannelMode.ForwardedErrorChannel)
        command = self._command()
        self._proc.start(command[0], command[1:])
        if not self._proc.waitForStarted(5_000):
            self._fail("无法启动服务器进程（pnpm 不在 PATH 中？）")
            return
        QTimer.singleShot(STARTUP_TIMEOUT_MS, self._on_startup_timeout)

    def stop(self) -> None:
        if self._state in (ServerState.STOPPED, ServerState.FAILED):
            self._set_state(ServerState.STOPPED)
            return
        self._intentional_stop = True
        self._emit_log("$ stopping server (SIGTERM)")
        if not self._proc.terminate():
            self._proc.kill()
        self._stop_timer.start(STOP_GRACE_MS)

    def restart(self) -> None:
        if self._state in (ServerState.READY, ServerState.STARTING):
            self._intentional_stop = False
            self._pending_restart = True
            self._emit_log("$ restarting server (SIGTERM)")
            if not self._proc.terminate():
                self._proc.kill()
            self._stop_timer.start(STOP_GRACE_MS)
        else:
            self.start()

    def attach(self, ready: ReadyInfo) -> None:
        """Attach to an externally started server (no process ownership)."""
        self._ready_info = ready
        self._set_state(ServerState.READY)
        self.ready.emit(ready)

    def target(self) -> tuple[str, str] | None:
        """Current (base, token) for the probe, or None when no ready server."""
        info = self._ready_info
        return (info.base, info.token) if info else None

    def shutdown(self) -> None:
        """Stop the process and wait for it to actually exit (app teardown)."""
        self.stop()
        if self._proc.state() != QProcess.ProcessState.NotRunning:
            self._proc.waitForFinished(STOP_GRACE_MS + 3_000)

    # -- internals -------------------------------------------------------------
    def _command(self) -> list[str]:
        cmd = list(self._config.server_command)
        # On Windows, pnpm is a batch script (pnpm.cmd), not pnpm.exe. Normalize
        # a bare "pnpm" so QProcess can find it (robust for older config files).
        if os.name == "nt" and cmd and cmd[0] == "pnpm":
            cmd[0] = "pnpm.cmd"
        return [*cmd, "--no-open", "--port", str(self._config.port)]

    @staticmethod
    def _port_free(port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                return True
            except OSError:
                return False

    def _emit_log(self, line: str) -> None:
        self._lines.append(line)
        self.log_line.emit(line)

    def _pump_stdout(self) -> None:
        while self._proc.bytesAvailable() > 0:
            self._line_buffer += bytes(self._proc.readAllStandardOutput()).decode("utf-8", "replace")
        while "\n" in self._line_buffer:
            line, self._line_buffer = self._line_buffer.split("\n", 1)
            self._handle_line(line)

    def _handle_line(self, line: str) -> None:
        ready = parse_ready_line(line)
        self._emit_log(mask_tokens(line))
        if ready is not None and not self._ready_seen:
            self._ready_seen = True
            self._ready_info = ready
            self._backoff_ms = 0
            self._set_state(ServerState.READY)
            self.ready.emit(ready)

    def _on_finished(self, exit_code: int, status: QProcess.ExitStatus) -> None:
        self._line_buffer = ""
        if self._intentional_stop or self._pending_restart:
            was_restart = self._pending_restart
            self._pending_restart = False
            self._intentional_stop = False
            self._ready_info = None
            self._set_state(ServerState.STOPPED)
            if was_restart:
                self.start()
            return
        # Unexpected exit.
        reason = f"server exited unexpectedly (code={exit_code}, status={status.name})"
        if self._ready_seen:
            self._set_state(ServerState.CRASHED)
            self._emit_log(f"!! {reason}")
            self._schedule_auto_restart(reason)
        else:
            self._fail(reason)

    def _on_error(self, error: QProcess.ProcessError) -> None:
        if self._state == ServerState.STARTING:
            self._fail(f"process error: {error.name}")

    def _on_startup_timeout(self) -> None:
        if self._state == ServerState.STARTING and not self._ready_seen:
            self._proc.kill()
            self._fail("启动超时（60s 内没有等到 token 行），见服务器日志")

    def _schedule_auto_restart(self, reason: str) -> None:
        if not self._config.auto_restart_on_crash:
            self.failure.emit(f"服务器崩溃（{reason}）；自动重启已关闭")
            return
        delay = self._backoff_ms or 1_000
        self._backoff_ms = min(delay * 2, MAX_BACKOFF_MS)
        self._emit_log(f"... auto-restart in {delay // 1_000}s")
        QTimer.singleShot(delay, self.start)

    def _enforce_stop(self) -> None:
        if self._state in (ServerState.STARTING, ServerState.READY, ServerState.CRASHED):
            if self._proc.state() != QProcess.ProcessState.NotRunning:
                self._proc.kill()

    def _fail(self, reason: str) -> None:
        self._ready_info = None
        self._set_state(ServerState.FAILED)
        self._emit_log(f"!! {reason}")
        self.failure.emit(reason)
