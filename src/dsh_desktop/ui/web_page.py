"""QWebEngine page subclass: external links go to the system browser.

Note (PySide6 6.12): scoped enum members are named with their type prefix,
so the old ``NavigationType.WebBrowserLink`` is now accessed via
``NavigationType['NavigationTypeLinkClicked']``.
"""
from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWebEngineCore import QWebEnginePage

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", ""}

_LINK_CLICKED = QWebEnginePage.NavigationType["NavigationTypeLinkClicked"]


class DshWebPage(QWebEnginePage):
    def __init__(self, profile, parent: QWebEnginePage | None = None) -> None:
        super().__init__(profile, parent)

    def acceptNavigationRequest(self, url: QUrl, nav_type, is_main_frame: bool) -> bool:
        # target=_blank / window.open links: leave the app only for non-local targets.
        if nav_type == _LINK_CLICKED:
            if url.host() not in _LOOPBACK_HOSTS:
                QDesktopServices.openUrl(url)
                return True
        return super().acceptNavigationRequest(url, nav_type, is_main_frame)

    def createWindow(self, window_type):  # noqa: N802 - Qt signature
        # We have no multi-window model; new-window requests are dropped
        # (non-loopback links already went to the system browser above).
        return None
