# Copyright (c) 2026, Dxbitz and contributors
"""Desk-facing helpers for the Synapse console page and the user shortcut.

None of this is part of the MCP endpoint. It backs two desk surfaces:

* the admin console (Page `synapse`, System Manager only), and
* the "Connect to Synapse" shortcut on a user's own profile, shown only when
  one of their roles is carried by a Synapse Profile.

The coverage check reads Synapse Profile with ignore_permissions on purpose: a
regular user cannot read that DocType, but they must still be told whether they
are covered and shown their own connect link. It returns a boolean and a URL,
never any profile data, so it leaks nothing a user could not infer by trying to
connect.
"""

import frappe

ENDPOINT_PATH = "/api/method/synapse.mcp.handle_mcp"
ADMIN_ROLE = "System Manager"


def endpoint_url() -> str:
	"""The absolute MCP endpoint URL for this site."""

	return frappe.utils.get_url(ENDPOINT_PATH)


def user_is_covered(user: str | None = None) -> bool:
	"""True if any of the user's roles is listed on an enabled Synapse Profile."""

	user = user or frappe.session.user
	if not user or user == "Guest":
		return False

	roles = set(frappe.get_roles(user))
	if not roles:
		return False

	enabled = frappe.get_all(
		"Synapse Profile", filters={"enabled": 1}, pluck="name", ignore_permissions=True
	)
	if not enabled:
		return False

	profile_roles = frappe.get_all(
		"Synapse Profile Role",
		filters={"parenttype": "Synapse Profile", "parent": ["in", enabled]},
		pluck="role",
		ignore_permissions=True,
	)
	return bool(roles & set(profile_roles))


# ── apps-screen gates ─────────────────────────────────────────────────────────
def has_admin_permission() -> bool:
	"""Gate for the Synapse tile on the /apps screen, System Manager only."""

	return ADMIN_ROLE in frappe.get_roles()


# ── whitelisted, for the desk JS ──────────────────────────────────────────────
@frappe.whitelist()
def connect_context() -> dict:
	"""What the connect shortcut and the console need to render.

	Available to any signed-in user. `covered` decides whether the user shortcut
	shows at all; `is_admin` unlocks the console actions.
	"""

	return {
		"endpoint": endpoint_url(),
		"covered": user_is_covered(),
		"is_admin": ADMIN_ROLE in frappe.get_roles(),
	}


@frappe.whitelist()
def readiness_report() -> str:
	"""The text of `check.report`, for the console's Health Check action.

	System Manager only, it reveals the site's whole Synapse configuration.
	"""

	frappe.only_for(ADMIN_ROLE)

	from synapse.mcp_tools import check

	return check.report_text()
