"""Parsing and sanitizing of `dsh web` stdout."""
from __future__ import annotations

import re
from dataclasses import dataclass

# The web app prints exactly one ready line per process:
#   dsh web: http://127.0.0.1:4567/?token=test-token
# The token is base64url (random bytes); anything else after `?token=` is not a
# ready line (e.g. a duplicated token param is refused by the server itself).
READY_RE = re.compile(r"^dsh web: (https?://\S+?)/\?token=([A-Za-z0-9._~+-]+)\s*$")

# Any `token=` value anywhere on a line is launch-credential material: mask it.
_TOKEN_RE = re.compile(r"(token=)(\S+)")


@dataclass(frozen=True)
class ReadyInfo:
    """A ready `dsh web` server: base origin plus its per-process launch token."""

    base: str  # e.g. http://127.0.0.1:4567 (no trailing slash, no query)
    token: str

    @property
    def url(self) -> str:
        return f"{self.base}/?token={self.token}"

    @property
    def ws_base(self) -> str:
        return self.base.replace("http://", "ws://").replace("https://", "wss://")


def parse_ready_line(line: str) -> ReadyInfo | None:
    """Extract the ready info from one stdout line, if it is the ready line."""
    m = READY_RE.match(line.strip())
    if m is None:
        return None
    return ReadyInfo(base=m.group(1).rstrip("/"), token=m.group(2))


def mask_tokens(line: str) -> str:
    """Replace every `token=<value>` on a line with `token=***`."""
    return _TOKEN_RE.sub(r"\1***", line)
