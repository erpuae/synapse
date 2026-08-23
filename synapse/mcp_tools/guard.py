# Copyright (c) 2026, Dxbitz and contributors
"""Read-only validation for SQL submitted through the MCP endpoint.

No frappe import, no I/O, no side effects — so every rule can be unit tested
without booting a site (the one sibling import, policy.ALWAYS_DENIED, is itself
pure stdlib). See tests/test_mcp_guard.py.

This is the *second* line of defence. The first is the read-only MariaDB user in
site_config (connection.py); that one is enforced by the database and cannot be
talked around. Everything here is text matching, so treat it as belt, not braces.

Design notes worth knowing before you edit:

* Comments are rejected, never stripped. Stripping is where the bypasses live.
* A blocked keyword is matched on word boundaries against the whole query, which
  means it also fires on identifiers that happen to contain the word. `tabCall
  Log` trips `call`, for example. That is a deliberate trade: a false rejection
  costs the caller one retry, a false acceptance costs a write.
"""

import re

from synapse.mcp_tools.policy import ALWAYS_DENIED

__all__ = ["UnsafeQuery", "MAX_QUERY_LENGTH", "BLOCKED_KEYWORDS", "BLOCKED_TABLES", "validate_read_only"]


MAX_QUERY_LENGTH = 5000

# Word-boundary matched against the whole query, case insensitive.
# `into` blocks SELECT ... INTO OUTFILE. It also blocks the rare SELECT ... INTO
# @var, which nothing here needs.
BLOCKED_KEYWORDS = (
	"insert",
	"update",
	"delete",
	"drop",
	"alter",
	"create",
	"truncate",
	"rename",
	"grant",
	"revoke",
	"replace",
	"call",
	"do",
	"handler",
	"load",
	"lock",
	"unlock",
	"set",
	"commit",
	"rollback",
	"savepoint",
	"start",
	"begin",
	"prepare",
	"execute",
	"deallocate",
	"analyze",
	"optimize",
	"repair",
	"flush",
	"kill",
	"shutdown",
	"sleep",
	"benchmark",
	# Named-lock functions carry an underscore, so a bare `lock` word-boundary
	# never fires on them. They cannot write, but a held lock is a timing side
	# channel, so block them by their full names.
	"get_lock",
	"release_lock",
	"release_all_locks",
	"is_free_lock",
	"is_used_lock",
	"outfile",
	"dumpfile",
	"load_file",
	"into",
)

# Case-insensitive substring match. Tables holding secrets, tokens or anything
# that would let a reader escalate. Derived from policy.ALWAYS_DENIED so the SQL
# tool and the document tools block exactly the same set and cannot drift — a
# DocType named there as "oauth client" becomes the table "taboauth client".
# `__auth` is a framework table, not a DocType, so it is added explicitly.
# Extend per site with the site_config key `mcp_sql_blocked_tables` rather than
# editing this tuple or ALWAYS_DENIED.
BLOCKED_TABLES = ("__auth",) + tuple(f"tab{name}" for name in sorted(ALWAYS_DENIED))

_COMMENT_MARKERS = ("--", "#", "/*", "*/")

_KEYWORD_RE = re.compile(r"\b(?:" + "|".join(BLOCKED_KEYWORDS) + r")\b", re.IGNORECASE)

# Leading whitespace and opening parentheses are stripped before the statement
# type is read, so `((SELECT 1))` is still recognised as a SELECT.
_LEADING_NOISE_RE = re.compile(r"^[\s(]+")

_ALLOWED_STATEMENTS = ("select", "with")


class UnsafeQuery(Exception):
	"""Raised when a submitted query fails one of the read-only rules.

	The message names the rule that fired — the caller hands it straight back to
	the model, which needs enough to correct itself on the next attempt.
	"""


def validate_read_only(query: str, extra_blocked_tables: tuple | list | None = None) -> str:
	"""Return the normalised query, or raise UnsafeQuery naming the rule that fired.

	Normalising means: outer whitespace trimmed and a single trailing semicolon
	removed. Nothing inside the statement is rewritten.
	"""

	if not isinstance(query, str):
		raise UnsafeQuery("Rule 'type': query must be a string.")

	stripped = query.strip()

	if not stripped:
		raise UnsafeQuery("Rule 'empty': query is empty.")

	# 1. Length cap — checked first so a pathological string is cheap to refuse.
	if len(stripped) > MAX_QUERY_LENGTH:
		raise UnsafeQuery(
			f"Rule 'length': query is {len(stripped)} characters, "
			f"the limit is {MAX_QUERY_LENGTH}."
		)

	# 2. No comments. Rejected outright, never stripped.
	for marker in _COMMENT_MARKERS:
		if marker in stripped:
			raise UnsafeQuery(
				f"Rule 'comment': query contains '{marker}'. "
				"Comments are not allowed — resubmit without them."
			)

	# 3. A single statement only. One trailing semicolon is tolerated.
	body = stripped[:-1].rstrip() if stripped.endswith(";") else stripped
	if ";" in body:
		raise UnsafeQuery(
			"Rule 'single statement': ';' may only appear as the final character. "
			"Submit one statement per call."
		)

	if not body:
		raise UnsafeQuery("Rule 'empty': query is empty.")

	# 4. Read-only statement types only.
	head = _LEADING_NOISE_RE.sub("", body).lower()
	if not head.startswith(_ALLOWED_STATEMENTS):
		first_word = (head.split(None, 1) or [""])[0] or "?"
		raise UnsafeQuery(
			f"Rule 'statement type': query starts with '{first_word}'. "
			"Only SELECT and WITH are permitted."
		)

	# 5. Blocked keywords, on word boundaries.
	if match := _KEYWORD_RE.search(body):
		raise UnsafeQuery(
			f"Rule 'keyword': query contains the blocked keyword '{match.group(0)}'. "
			"Note this also fires on identifiers containing the word."
		)

	# 6. Blocked tables, case-insensitive substring.
	lowered = body.lower()
	for table in _blocked_tables(extra_blocked_tables):
		if table in lowered:
			raise UnsafeQuery(f"Rule 'table': '{table}' is not readable through this tool.")

	return body


def _blocked_tables(extra: tuple | list | None) -> tuple:
	if not extra:
		return BLOCKED_TABLES

	extra_lowered = tuple(str(t).strip().lower() for t in extra if str(t).strip())
	return BLOCKED_TABLES + extra_lowered
