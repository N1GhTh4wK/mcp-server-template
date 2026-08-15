# mcp-server-template

A production-shaped starting point for [Model Context Protocol](https://modelcontextprotocol.io) servers — the pattern I use when adding a new tool surface to an agent platform.

Most MCP examples stop at "hello world". This one starts where real deployments get hard: **input validation, structured errors, output redaction, timeouts, and tests you can run before an agent ever touches it.**

## Why this shape

An MCP server is an *authority boundary*. The model decides what to call; your server decides what is actually allowed to happen. Three rules follow from that:

1. **Validate at the edge.** Never trust the argument object. Unknown parameter, wrong type, missing required field — reject before any side effect.
2. **Return errors as data, not exceptions.** A crashed tool teaches the model nothing. A structured `{"error": {...}}` lets it correct itself on the next turn.
3. **Redact on the way out.** The response is model context. Anything sensitive that leaves the server is permanently in the transcript.

## Layout

```
server.py            single-file server (PEP 723 inline deps — run with `uv run`)
tests/test_tools.py  adversarial tests: unknown param, wrong type, missing field, timeouts
```

## Run it

```bash
uv run server.py                 # stdio transport
uv run pytest tests/ -q          # tests
```

Register with any MCP client (Claude Desktop, Claude Code, your own agent runtime):

```json
{
  "mcpServers": {
    "example": { "command": "uv", "args": ["run", "/abs/path/server.py"] }
  }
}
```

## What to copy

- `@tool` registration with an explicit JSON Schema per tool — the schema *is* the contract.
- `validate_args()` — strict mode: unknown keys are an error, not a warning.
- `redact()` — allowlist the fields that may leave; everything else is dropped.
- The test file — run it against your own tools before enabling them. If an agent can crash your server with a malformed call, it will.

## Notes

Transport is stdio for simplicity. For HTTP deployments, put identity in front of the server (OAuth/OIDC) and keep per-client scopes — the tool layer should never be the only thing standing between a caller and an action.

## Related

Three parts of the same problem — how much an agent is allowed to do, and how you prove it behaves:

- **This repo** — the tool layer: validate, execute, redact.
- [agent-credential-broker](https://github.com/N1GhTh4wK/agent-credential-broker) — bounding an agent's **authority**: it requests actions, never credentials.
- [agent-eval-harness](https://github.com/N1GhTh4wK/agent-eval-harness) — bounding an agent's **judgement**: adversarial cases run before release.

MIT licensed. Built by [Hermann Ballesteros](https://www.linkedin.com/in/hermannballesteros) — CXO &amp; Partner, SLM Sistemas.
