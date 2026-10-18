"""Exchange the process launch token for an API operator cookie.

Official non-browser channel: ``GET /connect?token=<launch>&interactions=none``
answers 302 with a signed, authority-bound API cookie (valid 30 days).
"""
from __future__ import annotations

import httpx


class ProbeError(Exception):
    """The server refused or failed an API operation."""


def exchange_cookie(base: str, token: str, timeout: float = 5.0) -> str:
    """Return the raw ``name=value`` cookie string for this API peer."""
    url = f"{base}/connect"
    resp = httpx.get(
        url,
        params={"token": token, "interactions": "none"},
        follow_redirects=False,
        timeout=timeout,
    )
    if resp.status_code != 302:
        raise ProbeError(f"connect failed: HTTP {resp.status_code} on {url}")
    set_cookie = resp.headers.get("set-cookie", "")
    if "=" not in set_cookie:
        raise ProbeError("connect failed: no Set-Cookie in response")
    return set_cookie.split(";", 1)[0]
