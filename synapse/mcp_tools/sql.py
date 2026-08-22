# Copyright (c) 2026, Dxbitz and contributors
"""The read-only SQL tool — the escape hatch, not the front door.

Raw SQL bypasses Frappe's permission system completely, so this tool is not
part of the document toolset and does not share its allowlist. It is gated on
its own role, `MCP SQL Reader`, it is off until `enable_sql_tool` is ticked in
MCP Settings, and it should only ever be held by someone who already has direct
database access.

Reach for documents.py first. Use this when a question genuinely needs a join or
an aggregate that get_list cannot express, and accept that the answer ignores
every permission rule on the site.

Two layers stand behind it: the read-only MariaDB user in site_config
(connection.py), which the database enforces, and guard.py, which is text
matching. See the MCP section of the README.
"""

import re

import frappe

from synapse.mcp import mcp
from synapse.mcp_core import ToolAnnotations
from synapse.mcp_tools import audit, connection, serialise, settings
from synapse.mcp_tools.guard import UnsafeQuery, validate_read_only
from synapse.mcp_tools.policy import Denied

REQUIRED_ROLE = "MCP SQL Reader"
TIMEOUT_SECONDS = 15

# Matches a LIMIT that already closes the statement, with or without an offset:
#   ... LIMIT 10        ... LIMIT 10, 20        ... LIMIT 10 OFFSET 20
_TRAILING_LIMIT_RE = re.compile(r"\blimit\s+\d+\s*(?:,\s*\d+|offset\s+\d+)?\s*$", re.IGNORECASE)


@mcp.tool(
	roles=[REQUIRED_ROLE],
	annotations=ToolAnnotations(title="Run read-only SQL", readOnlyHint=True),
	enabled=settings.sql_tool_enabled,
)
@audit.audited(audit.SQL)
def run_sql_query(query: str, limit: int | None = None):
	"""Run a read-only SQL query against the ERPNext database and return rows.

	This ignores Frappe permissions entirely — prefer get_list and get_doc, and
	use this only for joins or aggregates they cannot express.

	Only SELECT and WITH statements are permitted. Table names follow the Frappe
	convention of `tab` plus the DocType name, for example `tabSales Invoice`.
	Child tables are separate tables joined on `parent`. Submitted documents have
	docstatus = 1, drafts 0, cancelled 2.

	Comments and multiple statements are rejected outright rather than cleaned
	up. A blocked keyword is matched on word boundaries against the whole query,
	so an identifier containing one is refused too — `tabCall Log` trips the
	`call` keyword, for instance. Dates come back in the format this site has
	configured for MCP, ISO by default.

	Args:
		query: A single SELECT or WITH statement. No semicolons, no comments.
		limit: Maximum rows to return. Clamped to the site's MCP row limit.
	"""

	entry = audit.current()
	entry.sql(query if isinstance(query, str) else str(query))

	# 1. Guard. A rejection goes back naming the rule so the caller can rewrite
	#    the query itself; it is never silently repaired here.
	try:
		normalised = validate_read_only(query, frappe.conf.get("mcp_sql_blocked_tables"))
		_check_frappe_layer(normalised)
	except UnsafeQuery as e:
		raise Denied(str(e)) from e

	# 2. Clamp the row cap, and append one when the query does not carry its own.
	applied_limit = settings.row_limit(limit)
	had_limit = bool(_TRAILING_LIMIT_RE.search(normalised))
	final_query = normalised if had_limit else f"{normalised} LIMIT {applied_limit}"

	# 3. Execute, on the read-only user where the site has one.
	if connection.is_configured():
		columns, rows = _run_read_only(final_query, applied_limit)
	else:
		columns, rows = _run_fallback(final_query, applied_limit)

	truncated = False
	if len(rows) > applied_limit:
		rows = rows[: applied_limit]
		truncated = True
	elif not had_limit and len(rows) == applied_limit:
		truncated = True

	rows = [serialise.to_client(dict(row), settings.output_formats()) for row in rows]
	entry.rows(len(rows))

	return {
		"row_count": len(rows),
		"truncated": truncated,
		"columns": columns,
		"rows": rows,
	}


def _run_read_only(query: str, limit: int):
	"""Run on the SELECT-only database user. The strong path."""

	with connection.read_only_cursor(TIMEOUT_SECONDS) as cursor:
		cursor.execute(query)
		columns = [d[0] for d in (cursor.description or [])]
		rows = list(cursor.fetchmany(limit + 1))

	return columns, rows


def _run_fallback(query: str, limit: int):
	"""Run on Frappe's own connection when no read-only user is configured.

	The site connection is read-write, so anything the guard failed to catch
	must not be allowed to persist. audit.audited rolls back on failure; the
	rollback here covers the success path too, since a SELECT has nothing worth
	keeping and an undetected write would.
	"""

	try:
		frappe.db.sql(f"SET SESSION max_statement_time = {float(TIMEOUT_SECONDS)}")
		rows = frappe.db.sql(query, as_dict=True)
	finally:
		frappe.db.rollback()

	rows = list(rows or [])[: limit + 1]
	columns = list(rows[0].keys()) if rows else []
	return columns, rows


def _check_frappe_layer(query: str):
	"""Run Frappe's own read-only check as an extra layer, where it applies.

	frappe.utils.safe_exec.check_safe_sql_query only whitelists SELECT and
	EXPLAIN — it does not understand CTEs, so a valid WITH query fails it. Our
	own guard is strictly stricter on WITH statements, so the upstream check is
	skipped there rather than being allowed to reject good queries.
	"""

	if query.lstrip("( \t\r\n").lower().startswith("with"):
		return

	try:
		from frappe.utils.safe_exec import check_safe_sql_query
	except ImportError:
		return

	if not check_safe_sql_query(query, throw=False):
		raise UnsafeQuery("Rule 'frappe': rejected by frappe's own read-only SQL check.")
