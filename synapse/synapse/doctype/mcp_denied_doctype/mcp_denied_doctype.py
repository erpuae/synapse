# Copyright (c) 2026, Dxbitz and contributors
"""One row of the MCP denylist. Child table of MCP Settings.

Every box ticked by default, so adding a DocType by name puts it entirely out of
reach. Untick Block Read to leave it readable while still refusing every change.

Only consulted when Access Mode is Denylist.
"""

from frappe.model.document import Document


class MCPDeniedDocType(Document):
	pass
