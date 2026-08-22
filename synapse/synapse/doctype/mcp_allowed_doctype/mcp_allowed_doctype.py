# Copyright (c) 2026, Dxbitz and contributors
"""One row of the MCP DocType allowlist. Child table of MCP Settings.

A tick here is a ceiling, not a grant: it says the action *may* be reached
through MCP, and the calling user still needs the matching Frappe permission.
"""

from frappe.model.document import Document


class MCPAllowedDocType(Document):
	pass
