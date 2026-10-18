"""Verify the restart race fix.

Starts a real dsh web server, triggers restart() after the first ready, and
checks that the NEW process survives past the 5s stop-grace period and becomes
ready again (instead of being SIGKILLed by a stale _enforce_stop timer).

PASS  => ready_count >= 2 and crashed_count == 0
FAIL  => the new process was killed (crashed_count > 0 / ready_count stays 1)
"""
from __future__ import annotations

import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from dsh_desktop.config import Config
from dsh_desktop.server.manager import ServerManager, ServerState

app = QApplication(sys.argv)
mgr = ServerManager(Config())
state = {"ready": 0, "crashed": 0}


def on_state(s: str) -> None:
    print(f"  state: {s}", flush=True)
    if s == ServerState.READY:
        state["ready"] += 1
    if s == ServerState.CRASHED:
        state["crashed"] += 1


def on_ready(info) -> None:
    print(f"  ready: {info.base}", flush=True)
    if state["ready"] == 1:
        print("  -> triggering restart()", flush=True)
        QTimer.singleShot(1_000, mgr.restart)


def finish() -> None:
    ok = state["ready"] >= 2 and state["crashed"] == 0
    print(f"\nRESULT ready_count={state['ready']} crashed_count={state['crashed']}", flush=True)
    print("PASS" if ok else "FAIL", flush=True)
    mgr.shutdown()
    app.quit()


mgr.state_changed.connect(on_state)
mgr.ready.connect(on_ready)
mgr.start()
QTimer.singleShot(45_000, finish)
app.exec()
