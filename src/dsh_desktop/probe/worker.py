"""Background probe: /connect cookie + session.list polling for native status.

Read-only by design (``interactions=none``): it only supplies the tray and
status bar. All interaction happens in the embedded web UI, which is the
browser peer.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QThread, Signal

from .connect import ProbeError, exchange_cookie
from .rpc import call

POLL_INTERVAL_S = 10.0


class ProbeWorker(QThread):
    """Polls session.list every few seconds and reports (phase, total, running, message)."""

    #: phase in {"down", "auth", "ok", "error"}; running = sessions with a live Agent
    status = Signal(str, int, int, str)

    def __init__(self, get_target, parent: QThread | None = None) -> None:
        """``get_target()`` returns the current (base, token) tuple or None."""
        super().__init__(parent)
        self._get_target = get_target
        self._stop = False

    def request_stop(self) -> None:
        self._stop = True

    def run(self) -> None:  # noqa: C901 - deliberate small state machine
        cookie = ""
        cookie_base: str | None = None
        backoff = POLL_INTERVAL_S
        while not self._stop:
            target = self._get_target()
            if target is None:
                cookie = ""
                cookie_base = None
                self.status.emit("down", 0, 0, "服务器未就绪")
                self._sleep(2.0)
                continue
            base, token = target
            if not cookie or base != cookie_base:
                try:
                    cookie = exchange_cookie(base, token)
                    cookie_base = base
                    backoff = POLL_INTERVAL_S
                except Exception as e:  # noqa: BLE001 - report any transport failure
                    self.status.emit("auth", 0, 0, str(e))
                    self._sleep(min(backoff, 5.0))
                    backoff = min(backoff * 2, 30.0)
                    continue
            try:
                # Typert Remote endpoints use slash separators: /api/session/list.
                # The wire field name is the Host parameter name: `_request`.
                value = call(base, cookie, "session/list", {"_request": {}}, timeout=15.0)
                items = value.get("items", []) if isinstance(value, dict) else []
                running = sum(
                    1 for it in items if isinstance(it, dict) and it.get("running")
                )
                self.status.emit("ok", len(items), running, "")
            except ProbeError as e:
                cookie = ""  # force re-exchange next round
                self.status.emit("error", 0, 0, str(e))
            self._sleep(POLL_INTERVAL_S)

    def _sleep(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while not self._stop and time.monotonic() < end:
            time.sleep(0.2)
