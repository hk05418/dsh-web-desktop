"""Unit tests for stdout capture (ready line parsing, token masking)."""
from dsh_desktop.server.capture import mask_tokens, parse_ready_line


def test_parse_ready_line():
    r = parse_ready_line("dsh web: http://127.0.0.1:4567/?token=abc-123")
    assert r is not None
    assert r.base == "http://127.0.0.1:4567"
    assert r.token == "abc-123"
    assert r.url == "http://127.0.0.1:4567/?token=abc-123"
    assert r.ws_base == "ws://127.0.0.1:4567"


def test_parse_ready_line_trailing_whitespace():
    r = parse_ready_line("  dsh web: https://10.0.0.7:8443/?token=xyz  \n")
    assert r is not None
    assert r.base == "https://10.0.0.7:8443"
    assert r.ws_base == "wss://10.0.0.7:8443"


def test_parse_non_ready_lines():
    assert parse_ready_line("dsh web: listening on 127.0.0.1 over plain HTTP; restrict…") is None
    assert parse_ready_line("dsh web: opening the default browser; pass --no-open") is None
    assert parse_ready_line("") is None
    assert parse_ready_line("dsh web: http://h/?token=a&token=b") is None


def test_mask_tokens():
    assert mask_tokens("dsh web: http://h/?token=secret123") == "dsh web: http://h/?token=***"
    assert mask_tokens("warn token=abc then text") == "warn token=*** then text"
    assert mask_tokens("no credentials here") == "no credentials here"
