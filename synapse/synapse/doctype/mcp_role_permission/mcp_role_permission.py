# Copyright (c) 2026, Dxbitz and contributors
"""One role's write grants through MCP. Child table of MCP Settings.

Reads need only the MCP Agent role. Everything else needs a role listed here
with the matching action ticked, on top of the DocType allowlist and the user's
own Frappe permissions.
"""

from frappe.model.document import Document


class MCPRolePermission(Document):
	pass
