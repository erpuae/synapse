# Copyright (c) 2026, Dxbitz and contributors
"""The document tools: read and write ERPNext data over MCP.

Every tool here runs **as the calling user with Frappe permissions on**. Nothing
uses ignore_permissions, nothing touches frappe.db directly, and writes go
through Document.insert/save/submit/cancel so validations, hooks and workflows
all fire exactly as they would in the desk. An agent using these tools can do
what its user can do, and no more.

On top of that sits the MCP allowlist (policy.py): the DocType must be listed
for the action, and the user must hold a role the site has granted that action
to. See the MCP section of the README.

Deliberately not exposed:

* `frappe.db.set_value` — skips validation and hooks. `set_value` here loads the
  document and saves it, so a scripted field stays correct.
* Arbitrary whitelisted method execution. That is a remote shell in a trenchcoat,
  and there is no allowlist granular enough to make it safe.
* Rename and amend. Add them when a real case turns up, with their own flags.
"""

import frappe

from synapse.mcp import mcp
from synapse.mcp_core import ToolAnnotations
from synapse.mcp_tools import audit, serialise, settings
from synapse.mcp_tools.policy import (
	ACTIONS,
	CANCEL,
	DELETE,
	DENYLIST,
	READ,
	SUBMIT,
	WRITE,
	Denied,
	actions_possible,
	check,
)

AGENT_ROLE = "MCP Agent"

# Fields the framework owns. Letting a caller set docstatus would turn update
# into an unaudited submit, which is the whole point of having a submit tool.
PROTECTED_FIELDS = frozenset(
	{
		"doctype",
		"docstatus",
		"name",
		"owner",
		"creation",
		"modified",
		"modified_by",
		"idx",
		"parent",
		"parenttype",
		"parentfield",
		"__islocal",
		"__unsaved",
	}
)

# Layout-only fieldtypes. Nothing an agent can read or write.
LAYOUT_FIELDTYPES = frozenset(
	{"Section Break", "Column Break", "Tab Break", "HTML", "Heading", "Button", "Fold"}
)

STANDARD_FIELDS = ("name", "owner", "creation", "modified", "modified_by", "docstatus", "idx")

_ORDER_DIRECTIONS = ("asc", "desc")


# ── discovery ─────────────────────────────────────────────────────────────────
@mcp.tool(
	roles=[AGENT_ROLE],
	annotations=ToolAnnotations(title="List reachable DocTypes", readOnlyHint=True),
	enabled=settings.read_tools_enabled,
)
@audit.audited(audit.READ)
def list_available_doctypes():
	"""List the DocTypes this endpoint can reach and what may be done to each.

	Call this first. The result already accounts for the site's allowlist and
	for the calling user's own roles, so anything absent here will be refused.
	It does not account for User Permissions, which are applied per record when
	a document is actually read or written.
	"""

	policy = settings.get_policy()
	roles = frappe.get_roles(frappe.session.user)

	if policy.mode == DENYLIST:
		return _denylist_summary(policy, roles)

	available = []
	for doctype in sorted(policy.doctypes):
		actions = []
		for action in ACTIONS:
			try:
				check(policy, action, doctype, roles)
			except Denied:
				continue
			actions.append(action)

		if actions:
			available.append({"doctype": doctype, "actions": actions})

	audit.current().rows(len(available))
	return {"doctypes": available, "count": len(available)}


@mcp.tool(
	roles=[AGENT_ROLE],
	annotations=ToolAnnotations(title="Describe a DocType", readOnlyHint=True),
	enabled=settings.read_tools_enabled,
)
@audit.audited(audit.READ)
def describe_doctype(doctype: str):
	"""Return the fields of a DocType, so a document can be read or built correctly.

	Layout fields are omitted. `options` carries the linked DocType for Link
	fields, the child DocType for Table fields, and the newline-separated choices
	for Select fields. Dates are returned in the format this site has configured
	for MCP, ISO by default; writes accept either ISO or DD-MM-YYYY whatever the
	output format is.

	Args:
		doctype: The DocType to describe, for example "Sales Invoice".
	"""

	doctype = _gate(READ, doctype)
	meta = frappe.get_meta(doctype)

	fields = [
		_field_info(df) for df in meta.fields if df.fieldtype not in LAYOUT_FIELDTYPES
	]

	audit.current().rows(len(fields))
	return {
		"doctype": doctype,
		"is_submittable": bool(meta.is_submittable),
		"is_tree": bool(getattr(meta, "is_tree", 0)),
		"title_field": meta.title_field,
		"standard_fields": list(STANDARD_FIELDS),
		"fields": fields,
	}


def _denylist_summary(policy, roles) -> dict:
	"""Discovery in denylist mode.

	Every DocType on the site is reachable, so listing them would return the
	whole schema and tell the model nothing useful. What it needs instead is
	which actions are possible at all, what is explicitly out of bounds, and
	that its own permissions are the real limit.
	"""

	possible = list(actions_possible(policy, roles))

	blocked = []
	for name in sorted(policy.denied):
		actions = sorted(policy.denied[name])
		blocked.append({"doctype": name, "blocked": actions})

	audit.current().rows(len(blocked))
	return {
		"mode": "denylist",
		"actions_possible": possible,
		"blocked_doctypes": blocked,
		"note": (
			"Every other DocType on this site is reachable for the actions listed in "
			"actions_possible, subject to your own Frappe permissions, which are applied "
			"per record. Token and credential DocTypes are always blocked, and schema, "
			"code and permission DocTypes are always read only. Use describe_doctype to "
			"see a DocType's fields."
		),
	}


def _field_info(df) -> dict:
	info = {
		"fieldname": df.fieldname,
		"label": df.label,
		"fieldtype": df.fieldtype,
	}

	if df.options:
		info["options"] = df.options
	if df.reqd:
		info["required"] = True
	if df.read_only:
		info["read_only"] = True
	if df.default:
		info["default"] = df.default

	return info


# ── reads ─────────────────────────────────────────────────────────────────────
@mcp.tool(
	roles=[AGENT_ROLE],
	annotations=ToolAnnotations(title="Get a document", readOnlyHint=True),
	enabled=settings.read_tools_enabled,
)
@audit.audited(audit.READ)
def get_doc(doctype: str, name: str):
	"""Fetch one whole document, child tables included.

	Args:
		doctype: The DocType, for example "Sales Invoice".
		name: The document name, for example "ACC-SINV-2026-00001".
	"""

	doctype = _gate(READ, doctype)
	audit.current().target(doctype, name)

	doc = frappe.get_doc(doctype, name)
	doc.check_permission("read")

	audit.current().rows(1)
	return {"doc": _document_dict(doc)}


@mcp.tool(
	roles=[AGENT_ROLE],
	annotations=ToolAnnotations(title="Get one field value", readOnlyHint=True),
	enabled=settings.read_tools_enabled,
)
@audit.audited(audit.READ)
def get_value(doctype: str, fieldname: str, name: str | None = None, filters: dict | None = None):
	"""Read a single field without pulling the whole document.

	Give either `name` for a specific document, or `filters` to match one.

	Args:
		doctype: The DocType to read from.
		fieldname: The field to return.
		name: The document name, when it is known.
		filters: Field/value pairs used to find the document instead. An
			operator may be given as a list, for example
			{"status": ["!=", "Closed"]}.
	"""

	doctype = _gate(READ, doctype)
	audit.current().target(doctype, name)

	if not name and not filters:
		raise Denied("Give either 'name' or 'filters'.")

	fields = _validate_fields(doctype, [fieldname])
	lookup = {"name": name} if name else _validate_filters(filters)

	rows = frappe.get_list(doctype, filters=lookup, fields=fields, limit_page_length=1)

	if not rows:
		audit.current().rows(0)
		return {"value": None, "found": False}

	audit.current().rows(1)
	return {"value": _out(rows[0].get(fieldname)), "found": True}


@mcp.tool(
	roles=[AGENT_ROLE],
	annotations=ToolAnnotations(title="List documents", readOnlyHint=True),
	enabled=settings.read_tools_enabled,
)
@audit.audited(audit.READ)
def get_list(
	doctype: str,
	filters: dict | None = None,
	fields: list | None = None,
	order_by: str | None = None,
	limit: int | None = None,
	start: int = 0,
):
	"""List documents the calling user is allowed to see.

	Permissions and User Permissions are applied, so this returns that user's
	view of the data and not the whole table.

	Args:
		doctype: The DocType to list.
		filters: Field/value pairs. An operator may be given as a list, for
			example {"posting_date": [">", "01-01-2026"]} or
			{"status": ["in", ["Open", "Overdue"]]}.
		fields: Field names to return. Defaults to name and the title field.
		order_by: "fieldname asc" or "fieldname desc".
		limit: Rows to return. Clamped to the site's MCP row limit.
		start: Rows to skip, for paging.
	"""

	doctype = _gate(READ, doctype)

	limit = settings.row_limit(limit)
	fields = _validate_fields(doctype, fields) if fields else _default_fields(doctype)

	rows = frappe.get_list(
		doctype,
		filters=_validate_filters(filters),
		fields=fields,
		order_by=_validate_order_by(doctype, order_by),
		limit_start=max(0, _as_int(start, 0)),
		limit_page_length=limit,
	)

	rows = [_out(dict(row)) for row in rows]

	audit.current().rows(len(rows))
	return {
		"rows": rows,
		"row_count": len(rows),
		"truncated": len(rows) == limit,
		"fields": fields,
	}


@mcp.tool(
	roles=[AGENT_ROLE],
	annotations=ToolAnnotations(title="Count documents", readOnlyHint=True),
	enabled=settings.read_tools_enabled,
)
@audit.audited(audit.READ)
def get_count(doctype: str, filters: dict | None = None):
	"""Count the documents the calling user is allowed to see.

	Args:
		doctype: The DocType to count.
		filters: Field/value pairs, same form as get_list.
	"""

	doctype = _gate(READ, doctype)

	rows = frappe.get_list(
		doctype,
		filters=_validate_filters(filters),
		fields=[{"COUNT": "name"}],
		limit_page_length=0,
	)

	# The returned key is the rendered SQL — "COUNT(`name`)" — so read the value
	# rather than guessing the key. frappe 16 refuses an aggregate written as a
	# plain string in `fields`, hence the dict form.
	total = int(next(iter((rows[0] or {}).values()), 0) or 0) if rows else 0

	audit.current().rows(total)
	return {"count": total}


# ── writes ────────────────────────────────────────────────────────────────────
@mcp.tool(
	roles=[AGENT_ROLE],
	# Additive: it adds a row and overwrites nothing, so destructiveHint stays
	# false. That is the honest distinction from update_doc, not a judgement that
	# creating matters less.
	annotations=ToolAnnotations(title="Create a document", readOnlyHint=False),
	enabled=settings.write_tools_enabled,
)
@audit.audited(audit.WRITE)
def create_doc(doctype: str, values: dict):
	"""Create and save a new document. It is left as a draft.

	Validations, hooks and naming series behave exactly as they do in the desk.
	Use submit_doc afterwards for a submittable DocType.

	Args:
		doctype: The DocType to create.
		values: Field values. Child tables are given as a list of objects, for
			example {"items": [{"item_code": "X", "qty": 1}]}.
	"""

	doctype = _gate(WRITE, doctype)
	audit.current().sent(values)

	doc = frappe.new_doc(doctype)
	doc.update(_prepare(doctype, values))
	doc.insert()

	audit.current().target(doctype, doc.name)
	audit.current().rows(1)
	return {"name": doc.name, "doctype": doctype, "docstatus": doc.docstatus}


@mcp.tool(
	roles=[AGENT_ROLE],
	annotations=ToolAnnotations(
		title="Update a document",
		readOnlyHint=False,
		# Destructive: it overwrites existing values, and a child table given
		# here replaces the whole table. Clients use this hint to decide how
		# firmly to confirm, and an update deserves at least the care of a
		# delete. idempotentHint is deliberately absent — repeating an update
		# whose payload contains a child table is not a no-op.
		destructiveHint=True,
	),
	enabled=settings.write_tools_enabled,
)
@audit.audited(audit.WRITE)
def update_doc(doctype: str, name: str, values: dict):
	"""Change fields on an existing document and save it.

	Only the fields given are touched. The before and after values of each are
	written to the MCP Access Log.

	Args:
		doctype: The DocType to update.
		name: The document name.
		values: Field values to set. Child tables given here replace the whole
			table, so send every row you want to keep.
	"""

	doctype = _gate(WRITE, doctype)
	audit.current().target(doctype, name)
	audit.current().sent(values)

	prepared = _prepare(doctype, values)

	doc = frappe.get_doc(doctype, name)
	doc.check_permission("write")

	before = {key: _out(doc.get(key)) for key in prepared}
	doc.update(prepared)
	doc.save()

	audit.current().changed(
		{
			key: {"from": before.get(key), "to": _out(doc.get(key))}
			for key in prepared
		}
	)
	audit.current().rows(1)
	return {"name": doc.name, "doctype": doctype, "updated_fields": sorted(prepared)}


@mcp.tool(
	roles=[AGENT_ROLE],
	annotations=ToolAnnotations(
		title="Set one field",
		readOnlyHint=False,
		# Overwrites whatever was in the field, so destructive, but repeating it
		# with the same value genuinely changes nothing further.
		destructiveHint=True,
		idempotentHint=True,
	),
	enabled=settings.write_tools_enabled,
)
@audit.audited(audit.WRITE)
def set_value(doctype: str, name: str, fieldname: str, value=None):
	"""Set a single field on a document and save it.

	This loads and saves the document rather than writing the column directly,
	so validations and hooks still run.

	Args:
		doctype: The DocType to update.
		name: The document name.
		fieldname: The field to set.
		value: The new value. Dates may be YYYY-MM-DD or DD-MM-YYYY.
	"""

	return update_doc.__wrapped__(doctype=doctype, name=name, values={fieldname: value})


@mcp.tool(
	roles=[AGENT_ROLE],
	annotations=ToolAnnotations(title="Submit a document", readOnlyHint=False, idempotentHint=True),
	enabled=settings.write_tools_enabled,
)
@audit.audited(audit.WRITE)
def submit_doc(doctype: str, name: str):
	"""Submit a draft document, moving it to docstatus 1.

	Args:
		doctype: The DocType to submit.
		name: The document name.
	"""

	doctype = _gate(SUBMIT, doctype)
	audit.current().target(doctype, name)

	doc = frappe.get_doc(doctype, name)
	doc.check_permission("submit")
	doc.submit()

	audit.current().rows(1)
	return {"name": doc.name, "doctype": doctype, "docstatus": doc.docstatus}


@mcp.tool(
	roles=[AGENT_ROLE],
	annotations=ToolAnnotations(title="Cancel a document", readOnlyHint=False, destructiveHint=True),
	enabled=settings.write_tools_enabled,
)
@audit.audited(audit.WRITE)
def cancel_doc(doctype: str, name: str):
	"""Cancel a submitted document, moving it to docstatus 2.

	Args:
		doctype: The DocType to cancel.
		name: The document name.
	"""

	doctype = _gate(CANCEL, doctype)
	audit.current().target(doctype, name)

	doc = frappe.get_doc(doctype, name)
	doc.check_permission("cancel")
	doc.cancel()

	audit.current().rows(1)
	return {"name": doc.name, "doctype": doctype, "docstatus": doc.docstatus}


@mcp.tool(
	roles=[AGENT_ROLE],
	annotations=ToolAnnotations(title="Delete a document", readOnlyHint=False, destructiveHint=True),
	enabled=settings.write_tools_enabled,
)
@audit.audited(audit.WRITE)
def delete_doc(doctype: str, name: str):
	"""Delete a document. Link checks apply, so a referenced document is refused.

	Args:
		doctype: The DocType to delete from.
		name: The document name.
	"""

	doctype = _gate(DELETE, doctype)
	audit.current().target(doctype, name)

	doc = frappe.get_doc(doctype, name)
	doc.check_permission("delete")
	# The snapshot is the only trace left once the row is gone.
	audit.current().sent(_document_dict(doc))

	frappe.delete_doc(doctype, name)

	audit.current().rows(1)
	return {"name": name, "doctype": doctype, "deleted": True}


# ── gates and validation ──────────────────────────────────────────────────────
def _gate(action: str, doctype: str) -> str:
	"""Resolve the DocType, run gate 3, record the target. Raises Denied.

	Resolving first matters. Models get capitalisation wrong constantly, and in
	denylist mode a name that reached the policy unresolved would be compared
	against the list as the caller spelled it. The policy matches case
	insensitively too, but the name also has to be right by the time it reaches
	the database, so it is canonicalised here once and used everywhere after.
	"""

	meta = _meta(doctype)

	if meta.istable:
		raise Denied(
			f"'{meta.name}' is a child table. Read or write it through its parent document."
		)

	resolved = check(
		settings.get_policy(),
		action,
		meta.name,
		frappe.get_roles(frappe.session.user),
	)
	audit.current().target(resolved)
	return resolved


def _meta(doctype: str):
	"""Frappe's meta for a DocType, or Denied if there is no such DocType."""

	if not doctype or not isinstance(doctype, str):
		raise Denied("A DocType is required.")

	try:
		return frappe.get_meta(doctype.strip())
	except Exception:
		raise Denied(f"'{doctype}' is not a DocType on this site.")


def _prepare(doctype: str, values) -> dict:
	"""Reject framework-owned fields, then convert dates for the database."""

	if not isinstance(values, dict) or not values:
		raise Denied("'values' must be a non-empty object of field names to values.")

	if blocked := sorted(set(values) & PROTECTED_FIELDS):
		raise Denied(
			f"These fields are managed by the framework and cannot be set here: "
			f"{', '.join(blocked)}. Use submit_doc or cancel_doc to change docstatus."
		)

	meta = frappe.get_meta(doctype)
	prepared = {}

	for key, value in values.items():
		df = meta.get_field(key)

		if df and df.fieldtype in ("Date", "Datetime"):
			value = serialise.to_db_date(value)
		elif df and df.fieldtype == "Table" and isinstance(value, list):
			value = [_prepare(df.options, row) for row in value if isinstance(row, dict)]

		prepared[key] = value

	return prepared


def _document_dict(doc) -> dict:
	"""A document as JSON, with password fields left out."""

	data = doc.as_dict(no_nulls=False)
	secret_fields = {df.fieldname for df in doc.meta.fields if df.fieldtype == "Password"}

	for fieldname in secret_fields:
		data.pop(fieldname, None)

	return _out(dict(data))


def _out(value):
	"""Convert a value for the client, in the date format this site has chosen."""

	return serialise.to_client(value, settings.output_formats())


def _validate_fields(doctype: str, fields) -> list:
	"""Allow plain field names only.

	frappe.get_list does its own validation, but accepting only names the meta
	knows about removes the whole class of expression-in-a-field-name tricks
	before it reaches the query builder.
	"""

	if not isinstance(fields, (list, tuple)):
		raise Denied("'fields' must be a list of field names.")

	meta = frappe.get_meta(doctype)
	known = {df.fieldname for df in meta.fields} | set(STANDARD_FIELDS)

	clean = []
	for field in fields:
		field = str(field).strip()
		if field not in known:
			raise Denied(f"'{field}' is not a field on {doctype}. Use describe_doctype to see them.")
		clean.append(field)

	if not clean:
		raise Denied("'fields' cannot be empty.")

	return clean


def _default_fields(doctype: str) -> list:
	meta = frappe.get_meta(doctype)
	fields = ["name"]

	if meta.title_field and meta.title_field != "name":
		fields.append(meta.title_field)

	if meta.is_submittable:
		fields.append("docstatus")

	return fields


def _validate_filters(filters):
	if filters is None:
		return {}

	if not isinstance(filters, dict):
		raise Denied("'filters' must be an object of field names to values.")

	return filters


def _validate_order_by(doctype: str, order_by):
	"""Only 'fieldname' or 'fieldname asc|desc'. Anything else is refused.

	order_by reaches the query builder as raw SQL, so it is the one string in
	this module that is checked rather than trusted.
	"""

	if not order_by:
		return "modified desc"

	parts = str(order_by).strip().split()
	if len(parts) > 2:
		raise Denied("'order_by' must be a field name, optionally followed by asc or desc.")

	fieldname = _validate_fields(doctype, [parts[0]])[0]
	direction = parts[1].lower() if len(parts) == 2 else "desc"

	if direction not in _ORDER_DIRECTIONS:
		raise Denied("'order_by' direction must be asc or desc.")

	return f"`tab{doctype}`.`{fieldname}` {direction}"


def _as_int(value, fallback: int) -> int:
	try:
		return int(value)
	except (TypeError, ValueError):
		return fallback
