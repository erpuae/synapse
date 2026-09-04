# Copyright (c) 2026, Dxbitz and contributors
"""Readiness check for the Synapse endpoint.

	bench --site <site> execute synapse.mcp_tools.check.report

Prints what is configured and what is missing, in the order it has to be fixed.
Everything it looks at is site configuration rather than app code, which is the
part `bench install-app` cannot do for you: the OAuth switches, the settings
switches, the Synapse Profiles that grant access, and the optional read-only
database user.

Read-only. It reports, it never changes anything. It reads the raw configuration
rather than a resolved policy, so what it shows is the site's setup, not any one
user's effective access.
"""

import frappe

from synapse.mcp_tools import connection, settings
from synapse.mcp_tools.policy import ACTIONS

OAUTH_FLAGS = (
	("show_auth_server_metadata", "OAuth server metadata (/.well-known/oauth-authorization-server)"),
	("show_protected_resource_metadata", "Protected resource metadata"),
	("enable_dynamic_client_registration", "Dynamic client registration"),
)


def report():
	"""Print the readiness report. Called from `bench execute`."""

	# Printed, not returned, `bench execute` echoes a return value, which would
	# dump the whole report a second time as one escaped string.
	print(report_text())


def report_text() -> str:
	"""Build the readiness report as one string. Reused by the console page."""

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
	s = frappe.get_single("Synapse Settings")
	lines.append("Synapse Settings")
	lines.append(f"  [{ok if s.enabled else no}] Endpoint enabled")
	lines.append(f"  [{ok if s.enable_read_tools else no}] Read tools")
	lines.append(f"  [{'  on  ' if s.enable_write_tools else ' off  '}] Write tools")
	lines.append(f"  [{'  on  ' if s.enable_sql_tool else ' off  '}] Read-only SQL tool (also needs a profile with Allow SQL)")
	lines.append(f"         Model provider: {settings.model_provider()}")
	lines.append(f"         Row limit: {settings.row_limit()}   Retention: {settings.retention_days()} days")
	lines.append("")

	# ── the backstop ──
	denied = [row for row in s.get("denied_doctypes") or [] if row.document_type]
	lines.append(f"Backstop, Blocked DocTypes ({len(denied)} entries)")
	for row in sorted(denied, key=lambda r: r.document_type or ""):
		blocked = [a for a in ACTIONS if row.get(f"deny_{a}")]
		lines.append(f"         {row.document_type}: blocks {', '.join(blocked) or 'nothing ticked'}")
	lines.append("         Plus always: token and credential DocTypes blocked outright,")
	lines.append("         schema, code and permission DocTypes read only.")
	lines.append("")

	# ── profiles, the grant ──
	profiles = frappe.get_all("Synapse Profile", fields=["name", "enabled", "full_access", "allow_sql"], order_by="name")
	enabled_profiles = [p for p in profiles if p.enabled]
	lines.append(f"Synapse Profiles ({len(enabled_profiles)} enabled of {len(profiles)})")
	if not enabled_profiles:
		lines.append(
			"  [" + no + "] No enabled profile, every document tool will refuse. "
			"Create a Synapse Profile, add roles and DocType access."
		)
	for p in profiles:
		doc = frappe.get_doc("Synapse Profile", p.name)
		roles = [r.role for r in doc.get("roles") or []]
		state = "enabled" if p.enabled else "disabled"
		flags = []
		if p.full_access:
			flags.append("FULL ACCESS")
		if p.allow_sql:
			flags.append("SQL")
		flag_str = f"  [{', '.join(flags)}]" if flags else ""
		lines.append(f"         {p.name} ({state}){flag_str}")
		lines.append(f"           roles: {', '.join(sorted(roles)) or 'none, grants nobody anything'}")
		if not p.full_access:
			access = doc.get("doctype_access") or []
			for row in sorted(access, key=lambda r: r.document_type or ""):
				actions = [a for a in ACTIONS if row.get(f"allow_{a}")]
				lines.append(f"           {row.document_type}: {', '.join(actions) or 'nothing ticked'}")
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

	return "\n".join(lines)
