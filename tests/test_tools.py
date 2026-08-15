"""Adversarial tests. Run these against your own tools before enabling them.

If an agent can crash your server with a malformed call, it eventually will —
usually at 3am, in production, on the one workflow nobody is watching.
"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import dispatch, validate_args, ToolError, redact  # noqa: E402


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# --- happy path -----------------------------------------------------------

def test_valid_call_returns_allowlisted_fields_only():
    out = run(dispatch("lookup_record", {"record_id": "R-1"}))
    assert out == {"id": "R-1", "title": "Record R-1", "status": "active"}
    assert "secret" not in out and "internal_owner" not in out


# --- the four failures every tool must survive ----------------------------

def test_unknown_parameter_is_rejected():
    out = run(dispatch("lookup_record", {"record_id": "R-1", "drop_table": True}))
    assert out["error"]["code"] == "unknown_parameter"


def test_missing_required_parameter_is_rejected():
    out = run(dispatch("lookup_record", {}))
    assert out["error"]["code"] == "missing_parameter"


def test_wrong_type_is_rejected():
    out = run(dispatch("lookup_record", {"record_id": 12345}))
    assert out["error"]["code"] == "invalid_type"


def test_unknown_tool_lists_alternatives():
    out = run(dispatch("definitely_not_a_tool", {}))
    assert out["error"]["code"] == "unknown_tool"
    assert "lookup_record" in out["error"]["available"]


# --- type-system edge cases ----------------------------------------------

def test_bool_does_not_satisfy_integer():
    schema = {"type": "object", "properties": {"n": {"type": "integer"}}}
    with pytest.raises(ToolError) as e:
        validate_args(schema, {"n": True})
    assert e.value.code == "invalid_type"


def test_enum_is_enforced():
    schema = {"type": "object", "properties": {"mode": {"type": "string",
                                                        "enum": ["fast", "slow"]}}}
    with pytest.raises(ToolError) as e:
        validate_args(schema, {"mode": "sideways"})
    assert e.value.code == "invalid_value"


# --- redaction ------------------------------------------------------------

def test_empty_allowlist_passes_through():
    assert redact({"a": 1, "b": 2}, set()) == {"a": 1, "b": 2}


def test_allowlist_drops_everything_else():
    assert redact({"a": 1, "secret": "x"}, {"a"}) == {"a": 1}


# --- resilience -----------------------------------------------------------

def test_handler_exception_becomes_structured_error(monkeypatch):
    from server import REGISTRY

    async def boom(_):
        raise RuntimeError("upstream exploded")

    monkeypatch.setattr(REGISTRY["lookup_record"], "handler", boom)
    out = run(dispatch("lookup_record", {"record_id": "R-1"}))
    assert out["error"]["code"] == "internal_error"
    assert "upstream exploded" not in str(out)   # no leaked internals


def test_timeout_is_reported_not_hung(monkeypatch):
    from server import REGISTRY

    async def slow(_):
        await asyncio.sleep(5)

    monkeypatch.setattr(REGISTRY["lookup_record"], "handler", slow)
    monkeypatch.setattr(REGISTRY["lookup_record"], "timeout_s", 0.05)
    out = run(dispatch("lookup_record", {"record_id": "R-1"}))
    assert out["error"]["code"] == "timeout"
