# Copyright (c) 2026, Dxbitz and contributors
"""Bulk editing for the MCP DocType allowlist (Access Mode = Allowlist).

Not needed in denylist mode — there you add the handful of DocTypes to block
straight into the MCP Settings grid, which is rather the point of that mode.

The allowlist has no wildcard on purpose — it fails closed, and a wildcard is
how a fail-closed design quietly stops being one. But a site that has decided to
lean on Frappe permissions instead should not have to tick a thousand grid rows
to say so, so this fills the table in one command:

	bench --site <site> execute synapse.mcp_tools.allowlist.show
	bench --site <site> execute synapse.mcp_tools.allowlist.grant_all
	bench --site <site> execute synapse.mcp_tools.allowlist.grant_all \\
		--kwargs "{'actions': 'read,write', 'dry_run': 1}"
	bench --site <site> execute synapse.mcp_tools.allowlist.grant \\
		--kwargs "{'doctypes': 'Task,Project', 'actions': 'read,write,delete'}"
	bench --site <site> execute synapse.mcp_tools.allowlist.clear

Understand what grant_all means before running it: with every DocType readable,
gate 3 stops narrowing anything and an agent's reach becomes exactly its user's
Frappe permissions. That is a legitimate choice — it is the model you get from
most MCP servers — but it is a choice, not a default, which is why it takes a
command rather than a tick.
"""

import frappe

from synapse.mcp_tools.policy import ACTIONS, ALWAYS_DENIED, ALWAYS_READ_ONLY

SETTINGS = "MCP Settings"

# The two built-in sets live in policy.py, which enforces them in denylist mode.
# grant_all applies the same ones so a site gets the same protection in either
# mode. They are stored lowercase there; DocType names are compared normalised.
NEVER = ALWAYS_DENIED
READ_ONLY_ALWAYS = ALWAYS_READ_ONLY


def _norm(name) -> str:
	return str(name or "").strip().lower()


def show():
	"""Print the current allowlist."""

	doc = frappe.get_single(SETTINGS)
	rows = doc.get("allowed_doctypes") or []

	print(f"MCP allowlist: {len(rows)} DocType(s) on {frappe.local.site}")
	print(f"Endpoint enabled: {bool(doc.enabled)}   Write tools: {bool(doc.enable_write_tools)}")

	for row in sorted(rows, key=lambda r: r.document_type or ""):
		granted = [a for a in ACTIONS if row.get(f"allow_{a}")]
		print(f"  {row.document_type}: {', '.join(granted) or 'nothing ticked'}")


def grant_all(actions="read", include_singles=1, dry_run=0):
	"""List every DocType on the site, with the given actions.

	Child tables are skipped — they are reached through their parent document,
	never on their own. Submit and cancel are only ticked where the DocType is
	actually submittable, so the table stays honest about what is possible.

	Args:
		actions: Comma-separated, from read, write, submit, cancel, delete.
		include_singles: Include Single DocTypes (settings pages). Default yes.
		dry_run: Report what would change and write nothing.
	"""

	wanted = _parse_actions(actions)
	candidates = frappe.get_all(
		"DocType",
		filters={"istable": 0},
		fields=["name", "issingle", "is_submittable"],
		order_by="name",
	)

	rows = []
	for dt in candidates:
		if _norm(dt.name) in NEVER:
			continue

		if dt.issingle and not int(include_singles or 0):
			continue

		granted = set(wanted)

		if _norm(dt.name) in READ_ONLY_ALWAYS:
			granted &= {"read"}

		if not dt.is_submittable:
			granted -= {"submit", "cancel"}

		if granted:
			rows.append((dt.name, granted))

	return _apply(rows, dry_run, label=f"all DocTypes ({', '.join(sorted(wanted))})")


def grant(doctypes, actions="read", dry_run=0):
	"""List specific DocTypes, replacing any existing row for each.

	Args:
		doctypes: Comma-separated DocType names.
		actions: Comma-separated, from read, write, submit, cancel, delete.
		dry_run: Report what would change and write nothing.
	"""

	wanted = _parse_actions(actions)
	names = [n.strip() for n in str(doctypes).split(",") if n.strip()]

	if not names:
		frappe.throw("Give at least one DocType.")

	rows = []
	for name in names:
		if not frappe.db.exists("DocType", name):
			frappe.throw(f"'{name}' is not a DocType on this site.")

		if _norm(name) in NEVER:
			print(f"  skipped {name} — never reachable through MCP")
			continue

		granted = set(wanted)
		if _norm(name) in READ_ONLY_ALWAYS:
			granted &= {"read"}
			print(f"  {name} — read only, whatever was asked for")

		if granted:
			rows.append((name, granted))

	return _apply(rows, dry_run, label=", ".join(names), merge=True)


def clear(dry_run=0):
	"""Empty the allowlist. The endpoint then permits nothing.

	Args:
		dry_run: Report what would change and write nothing.
	"""

	doc = frappe.get_single(SETTINGS)
	count = len(doc.get("allowed_doctypes") or [])

	if int(dry_run or 0):
		print(f"Would remove all {count} allowlist row(s).")
		return

	doc.set("allowed_doctypes", [])
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	print(f"Removed {count} allowlist row(s). The endpoint now permits nothing.")


def _apply(rows, dry_run, label: str, merge: bool = False):
	doc = frappe.get_single(SETTINGS)
	existing = {r.document_type: r for r in doc.get("allowed_doctypes") or []}

	if int(dry_run or 0):
		print(f"Would list {len(rows)} DocType(s) for {label}.")
		for name, granted in rows[:15]:
			print(f"  {name}: {', '.join(sorted(granted))}")
		if len(rows) > 15:
			print(f"  … and {len(rows) - 15} more")
		return

	if not merge:
		doc.set("allowed_doctypes", [])
		existing = {}

	for name, granted in rows:
		row = existing.get(name) or doc.append("allowed_doctypes", {"document_type": name})
		for action in ACTIONS:
			row.set(f"allow_{action}", 1 if action in granted else 0)

	doc.save(ignore_permissions=True)
	frappe.db.commit()

	print(f"Allowlist now holds {len(doc.allowed_doctypes)} DocType(s).")
	print("Reads work once 'Enable MCP Endpoint' is ticked and a user holds 'MCP Agent'.")
	print("Writes also need 'Enable Write Tools' plus a role granted the action in MCP Settings.")


def _parse_actions(actions) -> set:
	if isinstance(actions, str):
		actions = actions.split(",")

	wanted = {str(a).strip().lower() for a in actions or () if str(a).strip()}

	if unknown := sorted(wanted - set(ACTIONS)):
		frappe.throw(f"Unknown action(s): {', '.join(unknown)}. Valid: {', '.join(ACTIONS)}.")

	if not wanted:
		frappe.throw(f"Give at least one action from: {', '.join(ACTIONS)}.")

	return wanted
