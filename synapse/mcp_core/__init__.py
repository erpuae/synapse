# Copyright (c) 2026, Dxbitz and contributors
"""A small, dependency-free MCP (Model Context Protocol) server for Frappe apps.

Why this exists rather than `pip install frappe-mcp`:

* frappe-mcp 0.1.0 declares `pydantic~=2.11.7`, `werkzeug==3.1.3` and
  `click~=8.2.0`. Frappe 16 pins pydantic 2.12.5. Declaring the dependency makes
  `bench install-app`, `bench setup requirements` and `bench update` unsafe on
  any bench carrying this app. Vendoring removes that hazard — synapse
  installs with plain `bench install-app` and nothing else.
* Upstream has no per-tool authorization. Its `@mcp.tool` signature carries a
  `role` argument that is commented out. We need it, so it is implemented here:
  a tool declares the roles that may call it and is both hidden from
  `tools/list` and refused by `tools/call` for anyone else.
* No pydantic and no jsonschema on the request path. JSON-RPC envelopes are
  plain dicts and argument checking is a hundred lines of stdlib, which keeps a
  `tools/call` cheap.

Derived from frappe/frappe-mcp (MIT), trimmed to the parts this app uses:
JSON-RPC over a single Streamable HTTP POST, `initialize`, `ping`,
`tools/list`, `tools/call` and the notification sink. Prompts, resources,
completion and SSE streaming are not implemented — they return METHOD_NOT_FOUND
rather than pretending.
"""

from synapse.mcp_core.server import MCP, ToolAnnotations

__all__ = ["MCP", "ToolAnnotations"]
