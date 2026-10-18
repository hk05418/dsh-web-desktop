"""Unit tests for the /api RPC envelope handling (no network)."""
from dsh_desktop.probe.connect import ProbeError
from dsh_desktop.probe.rpc import build_request, parse_response


def test_build_request_shape():
    req = build_request("session/list", {})
    assert req["type"] == "client-request"
    assert req["method"] == "session/list"
    assert req["payload"] == {"args": {}}
    assert len(req["rpcId"]) == 32


def test_build_request_args_passthrough():
    req = build_request("session/create", {"location": "/tmp/x"})
    assert req["payload"]["args"] == {"location": "/tmp/x"}
    assert build_request("session/list")["payload"]["args"] == {}


def test_parse_response_ok():
    body = {
        "type": "server-response",
        "rpcId": "x",
        "result": {"ok": True, "value": {"items": [1, 2, 3]}},
    }
    assert parse_response("session/list", body) == {"items": [1, 2, 3]}


def test_parse_response_error():
    body = {
        "type": "server-response",
        "rpcId": "x",
        "result": {"ok": False, "error": {"code": "gateway/internal", "message": "boom"}},
    }
    try:
        parse_response("session/list", body)
        assert False, "expected ProbeError"
    except ProbeError as e:
        assert "gateway/internal" in str(e)
        assert "boom" in str(e)


def test_parse_response_wrong_type():
    try:
        parse_response("session/list", {"type": "server-event"})
        assert False, "expected ProbeError"
    except ProbeError:
        pass
