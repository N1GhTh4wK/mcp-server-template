# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp>=1.2.0"]
# ///
"""
MCP server template — validation, structured errors, redaction, timeouts.

Run:  uv run server.py
Test: uv run pytest tests/ -q
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

log = logging.getLogger("mcp.template")

# --------------------------------------------------------------------------
# Tool registry
# --------------------------------------------------------------------------

@dataclass
class Tool:
    name: str
    description: str
    schema: dict[str, Any]
    handler: Callable[[dict], Awaitable[dict]]
    timeout_s: float = 20.0
    # Allowlist of fields permitted to leave the server. Empty = pass through.
    returns: set[str] = field(default_factory=set)


REGISTRY: dict[str, Tool] = {}


def tool(name: str, description: str, schema: dict, *, timeout_s: float = 20.0,
         returns: set[str] | None = None):
    """Register a tool. The schema is the contract — keep it explicit."""
    def deco(fn: Callable[[dict], Awaitable[dict]]):
        REGISTRY[name] = Tool(name, description, schema, fn, timeout_s, returns or set())
        return fn
    return deco


# --------------------------------------------------------------------------
# Edge validation — strict by default
# --------------------------------------------------------------------------

class ToolError(Exception):
    def __init__(self, code: str, message: str, **detail):
        super().__init__(message)
        self.code, self.message, self.detail = code, message, detail

    def as_payload(self) -> dict:
        return {"error": {"code": self.code, "message": self.message, **self.detail}}


_PY_TYPES = {
    "string": str, "integer": int, "number": (int, float),
    "boolean": bool, "array": list, "object": dict,
}


def validate_args(schema: dict, args: dict) -> dict:
    """Reject unknown keys, wrong types and missing required fields.

    Deliberately strict: an agent that passes an unknown parameter is either
    hallucinating the interface or working from a stale schema. Both are worth
    surfacing loudly rather than silently ignoring.
    """
    props: dict = schema.get("properties", {})
    required: list = schema.get("required", [])

    unknown = sorted(set(args) - set(props))
    if unknown:
        raise ToolError("unknown_parameter",
                        f"Unknown parameter(s): {', '.join(unknown)}",
                        allowed=sorted(props))

    missing = [k for k in required if k not in args]
    if missing:
        raise ToolError("missing_parameter",
                        f"Missing required parameter(s): {', '.join(missing)}")

    for key, value in args.items():
        expected = props[key].get("type")
        py = _PY_TYPES.get(expected)
        # bool is a subclass of int in Python — do not let it satisfy "integer"
        if py and (not isinstance(value, py) or
                   (expected in ("integer", "number") and isinstance(value, bool))):
            raise ToolError("invalid_type",
                            f"Parameter '{key}' must be {expected}",
                            got=type(value).__name__)

        enum = props[key].get("enum")
        if enum and value not in enum:
            raise ToolError("invalid_value",
                            f"Parameter '{key}' must be one of {enum}", got=value)

    return args


def redact(payload: dict, allow: set[str]) -> dict:
    """Allowlist what may leave. The response becomes model context forever."""
    if not allow:
        return payload
    return {k: v for k, v in payload.items() if k in allow}


async def dispatch(name: str, args: dict) -> dict:
    """Single entry point: validate -> run with timeout -> redact.

    Errors are returned as data. A tool that raises teaches the model nothing;
    a structured error lets it correct itself on the next turn.
    """
    t = REGISTRY.get(name)
    if t is None:
        return ToolError("unknown_tool", f"No such tool: {name}",
                         available=sorted(REGISTRY)).as_payload()
    try:
        validate_args(t.schema, args)
        result = await asyncio.wait_for(t.handler(args), timeout=t.timeout_s)
        return redact(result, t.returns)
    except ToolError as e:
        return e.as_payload()
    except asyncio.TimeoutError:
        return ToolError("timeout", f"{name} exceeded {t.timeout_s}s").as_payload()
    except Exception as e:                      # never leak a stack trace to the model
        log.exception("tool %s failed", name)
        return ToolError("internal_error", f"{name} failed", kind=type(e).__name__).as_payload()


# --------------------------------------------------------------------------
# Example tool — replace with your own
# --------------------------------------------------------------------------

@tool(
    name="lookup_record",
    description="Fetch a record by id. Returns id, title and status only.",
    schema={
        "type": "object",
        "properties": {
            "record_id": {"type": "string", "description": "Record identifier"},
            "verbose": {"type": "boolean", "description": "Include extended fields"},
        },
        "required": ["record_id"],
    },
    returns={"id", "title", "status"},   # internal_owner / secret are dropped
)
async def lookup_record(args: dict) -> dict:
    rid = args["record_id"]
    # Replace with a real lookup. Note the response carries fields that the
    # allowlist removes — that is the point: safety does not depend on the
    # data layer being careful.
    return {
        "id": rid,
        "title": f"Record {rid}",
        "status": "active",
        "internal_owner": "ops-team@internal",   # dropped by `returns`
        "secret": "never-leaves",                # dropped by `returns`
    }


# --------------------------------------------------------------------------
# MCP wiring
# --------------------------------------------------------------------------

def build_server():
    from mcp.server import Server
    from mcp.types import TextContent, Tool as MCPTool

    server = Server("mcp-server-template")

    @server.list_tools()
    async def list_tools() -> list[MCPTool]:
        return [MCPTool(name=t.name, description=t.description, inputSchema=t.schema)
                for t in REGISTRY.values()]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        payload = await dispatch(name, arguments or {})
        return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))]

    return server


async def main() -> None:
    from mcp.server.stdio import stdio_server
    server = build_server()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
