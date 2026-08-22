# Copyright (c) 2026, Dxbitz and contributors
"""Readiness check for the MCP endpoint.

	bench --site <site> execute synapse.mcp_tools.check.report

Prints what is configured and what is missing, in the order it has to be fixed.
Everything it looks at is site configuration rather than app code, which is the
part `bench install-app` cannot do for you: the OAuth switches, the role
assignments, the allowlist and the optional read-only database user.

Read-only. It reports, it never changes anything.
"""

import frappe

from synapse.mcp_tools import connection, settings
from synapse.mcp_tools.policy import ACTIONS, DENYLIST

OAUTH_FLAGS = (
	("show_auth_server_metadata", "OAuth server metadata (/.well-known/oauth-authorization-server)"),
	("show_protected_resource_metadata", "Protected resource metadata"),
	("enable_dynamic_client_registration", "Dynamic client registration"),
)

AGENT_ROLE = "MCP Agent"
SQL_ROLE = "MCP SQL Reader"


def report():
	lines = []
	ok = "  ok  "
	no = " MISS "

	lines.append(f"Endpoint: /api/method/synapse.mcp.handle_mcp  (site: {frappe.local.site})")
	lines.append("")

	# ── OAuth ──
	lines.append("OAuth (needed for an MCP client to connect without a hand-made OAuth Client)")
	for fieldname, label in OAUTH_FLAGS:
		on = bool(frappe.db.get_single_value("OAuth Settings", fieldname))
		lines.append(f"  [{ok if on else no}] {label}")
	lines.append("            Turn these on in OAuth Settings. Nothing in this app changes them.")
	lines.append("")

	# ── settings ──
	policy = settings.get_policy()
	lines.append("MCP Settings")
	lines.append(f"  [{ok if policy.enabled else no}] Endpoint enabled")
	lines.append(f"  [{ok if policy.read_enabled else no}] Read tools")
	lines.append(f"  [{'  on  ' if policy.write_enabled else ' off  '}] Write tools")
	lines.append(f"  [{'  on  ' if settings.sql_tool_enabled() else ' off  '}] Read-only SQL tool")
	lines.append(f"         Row limit: {settings.row_limit()}   Retention: {settings.retention_days()} days")
	lines.append(f"         Access mode: {policy.mode}")
	lines.append("")

	# ── the access list, whichever one is in force ──
	if policy.mode == DENYLIST:
		lines.append(f"DocType denylist ({len(policy.denied)} entries)")
		lines.append("         Everything not listed is reachable. The user's own Frappe")
		lines.append("         permissions are the working boundary.")
		for name in sorted(policy.denied):
			lines.append(f"         {name}: blocked for {', '.join(sorted(policy.denied[name]))}")
		lines.append("         Plus always: token and credential DocTypes blocked outright,")
		lines.append("         schema, code and permission DocTypes read only.")
	else:
		lines.append(f"DocType allowlist ({len(policy.doctypes)} entries)")
		if not policy.doctypes:
			lines.append(
				"  [" + no + "] Empty — every document tool will refuse. Add DocTypes in "
				"MCP Settings, or switch Access Mode to Denylist."
			)
		for name in sorted(policy.doctypes):
			rule = policy.doctypes[name]
			actions = [a for a in ACTIONS if rule.allows(a)]
			lines.append(f"         {name}: {', '.join(actions) or 'nothing ticked'}")
	lines.append("")

	# ── roles ──
	lines.append("Roles granted write actions in MCP Settings")
	if not policy.role_actions:
		lines.append("         none — the endpoint is read-only whatever the switches say")
	for role, actions in sorted(policy.role_actions.items()):
		lines.append(f"         {role}: {', '.join(sorted(actions))}")
	lines.append("")

	# ── role holders ──
	lines.append("Role holders")
	for role in (AGENT_ROLE, SQL_ROLE):
		exists = bool(frappe.db.exists("Role", role))
		holders = (
			frappe.get_all("Has Role", filters={"role": role, "parenttype": "User"}, pluck="parent")
			if exists
			else []
		)
		mark = ok if exists else no
		lines.append(f"  [{mark}] {role}: {len(holders)} user(s) {sorted(holders) or ''}")
	lines.append("")

	# ── read-only database user ──
	lines.append("Read-only database user (SQL tool only)")
	if connection.is_configured():
		lines.append(f"  [{ok}] site_config has mcp_ro_db_user / mcp_ro_db_password")
	else:
		lines.append(
			f"  [{no}] Not configured. The SQL tool would fall back to the site's read-write "
			"connection with a rollback, leaving guard.py as the only boundary."
		)

	# Printed, not returned — `bench execute` echoes a return value, which would
	# dump the whole report a second time as one escaped string.
	print("\n".join(lines))
