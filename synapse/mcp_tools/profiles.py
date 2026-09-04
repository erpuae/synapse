# Copyright (c) 2026, Dxbitz and contributors
"""Bulk editing for a Synapse Profile's DocType Access grid.

A profile is the unit of access: it lists roles, and the DocTypes and actions
those roles may reach. Small profiles are quicker to build in the desk, but a
site that wants an agent to reach most of the schema should not have to tick
hundreds of grid rows, so this fills one profile's grid in a single command:

	bench --site <site> execute synapse.mcp_tools.profiles.show \\
		--kwargs "{'profile': 'Reporting'}"
	bench --site <site> execute synapse.mcp_tools.profiles.grant_all \\
		--kwargs "{'profile': 'Reporting', 'actions': 'read'}"
	bench --site <site> execute synapse.mcp_tools.profiles.grant \\
		--kwargs "{'profile': 'Sales Agent', 'doctypes': 'Sales Invoice,Customer', 'actions': 'read,write,submit'}"
	bench --site <site> execute synapse.mcp_tools.profiles.clear \\
		--kwargs "{'profile': 'Reporting'}"

For "reach everything, let Frappe permissions be the limit", tick Full Access on
the profile instead, it says that in one box rather than 700 rows, and it stays
correct as the schema grows. grant_all is for the middle ground: a broad but
enumerated grid you can then trim.

The two built-in protection sets in policy.py still apply to grant_all, so a
credential DocType is never listed and a schema/code DocType is listed read only.
"""

import frappe

from synapse.mcp_tools.policy import ACTIONS, ALWAYS_DENIED, ALWAYS_READ_ONLY

PROFILE_DOCTYPE = "Synapse Profile"

# The built-in sets live in policy.py, which enforces them as the backstop.
# grant_all applies the same ones so a bulk fill gets the same protection.
NEVER = ALWAYS_DENIED
READ_ONLY_ALWAYS = ALWAYS_READ_ONLY


def _norm(name) -> str:
	return str(name or "").strip().lower()


def _profile(name):
	if not name:
		frappe.throw("Give a profile name, for example {'profile': 'Reporting'}.")
	if not frappe.db.exists(PROFILE_DOCTYPE, name):
		frappe.throw(f"'{name}' is not a Synapse Profile. Create it first in the desk.")
	return frappe.get_doc(PROFILE_DOCTYPE, name)


def show(profile=None):
	"""Print a profile's DocType Access."""

	doc = _profile(profile)
	rows = doc.get("doctype_access") or []

	print(f"Synapse Profile '{doc.name}' on {frappe.local.site}")
	print(f"Enabled: {bool(doc.enabled)}   Full Access: {bool(doc.full_access)}   Allow SQL: {bool(doc.allow_sql)}")
	print(f"Roles: {', '.join(r.role for r in doc.get('roles') or []) or 'none'}")

	if doc.full_access:
		print("Full Access is on, so the grid below is ignored.")
	for row in sorted(rows, key=lambda r: r.document_type or ""):
		granted = [a for a in ACTIONS if row.get(f"allow_{a}")]
		print(f"  {row.document_type}: {', '.join(granted) or 'nothing ticked'}")


def grant_all(profile=None, actions="read", include_singles=1, dry_run=0):
	"""List every DocType on the site in the profile, with the given actions.

	Child tables are skipped, they are reached through their parent document.
	Submit and cancel are only ticked where the DocType is actually submittable.

	Args:
		profile: The Synapse Profile to fill.
		actions: Comma-separated, from read, write, submit, cancel, delete, operate.
		include_singles: Include Single DocTypes (settings pages). Default yes.
		dry_run: Report what would change and write nothing.
	"""

	doc = _profile(profile)
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

	return _apply(doc, rows, dry_run, label=f"all DocTypes ({', '.join(sorted(wanted))})")


def grant(profile=None, doctypes=None, actions="read", dry_run=0):
	"""List specific DocTypes in the profile, replacing any existing row for each.

	Args:
		profile: The Synapse Profile to fill.
		doctypes: Comma-separated DocType names.
		actions: Comma-separated, from read, write, submit, cancel, delete, operate.
		dry_run: Report what would change and write nothing.
	"""

	doc = _profile(profile)
	wanted = _parse_actions(actions)
	names = [n.strip() for n in str(doctypes or "").split(",") if n.strip()]

	if not names:
		frappe.throw("Give at least one DocType.")

	rows = []
	for name in names:
		if not frappe.db.exists("DocType", name):
			frappe.throw(f"'{name}' is not a DocType on this site.")

		if _norm(name) in NEVER:
			print(f"  skipped {name}, never reachable through Synapse")
			continue

		granted = set(wanted)
		if _norm(name) in READ_ONLY_ALWAYS:
			granted &= {"read"}
			print(f"  {name}, read only, whatever was asked for")

		if granted:
			rows.append((name, granted))

	return _apply(doc, rows, dry_run, label=", ".join(names), merge=True)


def clear(profile=None, dry_run=0):
	"""Empty a profile's DocType Access grid.

	Args:
		profile: The Synapse Profile to clear.
		dry_run: Report what would change and write nothing.
	"""

	doc = _profile(profile)
	count = len(doc.get("doctype_access") or [])

	if int(dry_run or 0):
		print(f"Would remove all {count} access row(s) from '{doc.name}'.")
		return

	doc.set("doctype_access", [])
	doc.save()
	frappe.db.commit()
	print(f"Removed {count} access row(s) from '{doc.name}'.")


def _apply(doc, rows, dry_run, label: str, merge: bool = False):
	existing = {r.document_type: r for r in doc.get("doctype_access") or []}

	if int(dry_run or 0):
		print(f"Would list {len(rows)} DocType(s) in '{doc.name}' for {label}.")
		for name, granted in rows[:15]:
			print(f"  {name}: {', '.join(sorted(granted))}")
		if len(rows) > 15:
			print(f"  ... and {len(rows) - 15} more")
		return

	if not merge:
		doc.set("doctype_access", [])
		existing = {}

	for name, granted in rows:
		row = existing.get(name) or doc.append("doctype_access", {"document_type": name})
		for action in ACTIONS:
			row.set(f"allow_{action}", 1 if action in granted else 0)

	doc.save()
	frappe.db.commit()

	print(f"Profile '{doc.name}' now lists {len(doc.doctype_access)} DocType(s).")
	print("Reads work once 'Enable Synapse Endpoint' and 'Enable Read Tools' are ticked in Synapse Settings")
	print("and a user holds one of this profile's roles. Writes also need 'Enable Write Tools'.")


def _parse_actions(actions) -> set:
	if isinstance(actions, str):
		actions = actions.split(",")

	wanted = {str(a).strip().lower() for a in actions or () if str(a).strip()}

	if unknown := sorted(wanted - set(ACTIONS)):
		frappe.throw(f"Unknown action(s): {', '.join(unknown)}. Valid: {', '.join(ACTIONS)}.")

	if not wanted:
		frappe.throw(f"Give at least one action from: {', '.join(ACTIONS)}.")

	return wanted
