# Copyright (c) 2026, Dxbitz and contributors
# For licence information, please see LICENSE
"""Set-up run by `bench install-app synapse`.

The roles are created here rather than in a patch. Frappe records an app's
patches as already applied when the app is first installed — the schema is
current by definition, so there is nothing to migrate — which means a patch
would never run for a new installation. after_install is the hook that does.

Everything here is idempotent, so re-running it is safe.
"""

import frappe

ROLES = {
	# Gates the document tools. Holding it grants no data access on its own:
	# every read and write still passes the DocType access list in MCP Settings
	# and then the user's own Frappe permissions. What it grants is the ability
	# to reach the site through an agent at all, which is worth deciding per
	# user rather than by default.
	"MCP Agent": {"desk_access": 0},
	# Gates the raw SQL tool, which bypasses Frappe permissions completely. A
	# holder can read every table on the site regardless of their DocType
	# permissions. Grant it only to people who already have database access.
	"MCP SQL Reader": {"desk_access": 1},
}


def after_install():
	create_roles()


def create_roles():
	"""Create the MCP roles, empty and assigned to nobody."""

	for role_name, options in ROLES.items():
		if frappe.db.exists("Role", role_name):
			continue

		frappe.get_doc(
			{
				"doctype": "Role",
				"role_name": role_name,
				"is_custom": 1,
				**options,
			}
		).insert(ignore_permissions=True)

	frappe.db.commit()
