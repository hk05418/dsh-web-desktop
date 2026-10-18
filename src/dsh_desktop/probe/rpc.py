"""Unary Remote RPC over the ``/api`` HTTP bridge (JSON envelopes)."""
from __future__ import annotations

import uuid
from typing import Any

import httpx

from .connect import ProbeError


def build_request(method: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build one ``client-request`` envelope."""
    return {
        "type": "client-request",
        "rpcId": uuid.uuid4().hex,
        "method": method,
        "payload": {"args": args or {}},
    }


def parse_response(method: str, body: dict[str, Any]) -> Any:
    """Validate a ``server-response`` envelope and return its value."""
    if body.get("type") != "server-response":
        raise ProbeError(f"{method}: unexpected response type {body.get('type')!r}")
    result = body.get("result")
    if not isinstance(result, dict) or not result.get("ok"):
        error = (result or {}).get("error", {})
        raise ProbeError(f"{method}: {error.get('code', '?')}: {error.get('message', '?')}")
    return result.get("value")


def call(base: str, cookie: str, method: str, args: dict[str, Any] | None = None,
         timeout: float = 30.0) -> Any:
    """Invoke one unary Remote endpoint and return its value."""
    resp = httpx.post(
        f"{base}/api/{method}",
        json=build_request(method, args),
        headers={"cookie": cookie, "content-type": "application/json"},
        timeout=timeout,
    )
    if resp.status_code == 401:
        raise ProbeError(f"{method}: unauthorized (server restarted or cookie expired)")
    if resp.status_code == 404:
        raise ProbeError(f"{method}: endpoint not found")
    if resp.status_code >= 400:
        raise ProbeError(f"{method}: HTTP {resp.status_code}")
    return parse_response(method, resp.json())
