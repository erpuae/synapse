# Copyright (c) 2026, Dxbitz and contributors
"""The synapse MCP endpoint.

	POST https://<site>/api/method/synapse.mcp.handle_mcp

Authentication is Frappe's own, so an OAuth2 bearer token, an API key or a desk
session cookie all work. Frappe 16 publishes OAuth server metadata and supports
dynamic client registration, which is what lets an MCP client connect without an
OAuth Client record being made by hand — see the README for the three OAuth
Settings switches that has to be turned on.

`allow_guest` is left at False, so an unauthenticated POST is refused by the
framework before any tool code runs. Everything past that point is per tool:
a role on the tool itself, then the MCP allowlist, then Frappe's permissions.

The server is vendored in synapse/mcp_core rather than installed from
frappe-mcp; that module's docstring explains why.
"""

import synapse
from synapse.mcp_core import MCP

def _record_refusal(tool_name, reason, tool):
	"""Keep refused calls in the audit trail.

	mcp_core turns a call away before the tool body runs when the tool is
	unknown or switched off, when the caller lacks its role, or when the
	arguments do not fit the schema. The tool's own @audited wrapper never gets
	to run in those cases, so the row is written from here instead.
	"""

	from synapse.mcp_tools import audit

	kind = getattr(getattr(tool, "fn", None), "_mcp_kind", None)
	audit.refused(tool_name, reason, kind)


mcp = MCP(
	"synapse",
	version=getattr(synapse, "__version__", "1.0.0"),
	on_refusal=_record_refusal,
)


@mcp.register()
def handle_mcp():
	"""Entry point for MCP requests. Body is imports only.

	This runs before every JSON-RPC call, `ping` and `initialize` included, and
	importing the tool modules is what fills the registry. Anything heavier than
	an import here is paid on every single call.
	"""

	import synapse.mcp_tools.documents  # noqa: F401
	import synapse.mcp_tools.sql  # noqa: F401
