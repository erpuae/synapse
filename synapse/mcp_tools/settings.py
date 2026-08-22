# Copyright (c) 2026, Dxbitz and contributors
"""Reads MCP Settings and turns it into the pure Policy that policy.py checks.

Cached on frappe.local for the life of the request. MCP Settings is a Single so
frappe.get_cached_doc already serves it from redis; the local cache saves
rebuilding the dataclasses on every tool call in a multi-call request.
"""

import frappe

from synapse.mcp_tools.policy import ACTIONS, ALLOWLIST, MODES, DocTypeRule, Policy
from synapse.mcp_tools.serialise import DMY, ISO, Formats

SETTINGS_DOCTYPE = "MCP Settings"
CACHE_KEY = "_synapse_mcp_policy"

# The site can lower these in MCP Settings but never raise them past here.
HARD_ROW_CAP = 500
DEFAULT_ROW_LIMIT = 100
DEFAULT_RETENTION_DAYS = 90


def get_policy() -> Policy:
	"""Return this request's Policy, building it once."""

	cached = getattr(frappe.local, CACHE_KEY, None)
	if cached is not None:
		return cached

	policy = _build()
	setattr(frappe.local, CACHE_KEY, policy)
	return policy


def clear_cache():
	"""Called from MCP Settings.on_update so an edit takes effect immediately."""

	if hasattr(frappe.local, CACHE_KEY):
		delattr(frappe.local, CACHE_KEY)


def _build() -> Policy:
	try:
		doc = frappe.get_cached_doc(SETTINGS_DOCTYPE)
	except Exception:
		# Not migrated yet, or the DocType is gone. Deny everything rather than
		# defaulting open.
		return Policy()

	doctypes = {}
	for row in doc.get("allowed_doctypes") or []:
		if not row.document_type:
			continue

		doctypes[row.document_type] = DocTypeRule(
			read=bool(row.allow_read),
			write=bool(row.allow_write),
			submit=bool(row.allow_submit),
			cancel=bool(row.allow_cancel),
			delete=bool(row.allow_delete),
		)

	denied = {}
	for row in doc.get("denied_doctypes") or []:
		if not row.document_type:
			continue

		blocked = {action for action in ACTIONS if row.get(f"deny_{action}")}
		if blocked:
			denied[row.document_type] = frozenset(blocked)

	role_actions = {}
	for row in doc.get("role_permissions") or []:
		if not row.role:
			continue

		granted = {action for action in ACTIONS if action != "read" and row.get(f"allow_{action}")}
		if granted:
			role_actions[row.role] = frozenset(granted)

	# A site saved before the mode field existed has it empty. Allowlist is the
	# safe reading of that, and it is what those sites were actually doing.
	mode = doc.access_mode if doc.access_mode in MODES else ALLOWLIST

	return Policy(
		enabled=bool(doc.enabled),
		read_enabled=bool(doc.enable_read_tools),
		write_enabled=bool(doc.enable_write_tools),
		mode=mode,
		doctypes=doctypes,
		denied=denied,
		role_actions=role_actions,
	)


# ── predicates used as `enabled=` on tool registrations ───────────────────────
def read_tools_enabled() -> bool:
	policy = get_policy()
	return policy.enabled and policy.read_enabled


def write_tools_enabled() -> bool:
	policy = get_policy()
	return policy.enabled and policy.write_enabled


def sql_tool_enabled() -> bool:
	if not get_policy().enabled:
		return False

	return bool(_value("enable_sql_tool"))


# ── numeric settings ──────────────────────────────────────────────────────────
def row_limit(requested=None) -> int:
	"""Clamp a caller's requested row count to the site's cap, then the hard cap."""

	site_cap = _int(_value("max_rows"), DEFAULT_ROW_LIMIT)
	site_cap = max(1, min(site_cap, HARD_ROW_CAP))

	if requested is None:
		return site_cap

	return max(1, min(_int(requested, site_cap), site_cap))


def output_formats() -> Formats:
	"""The date and datetime patterns this site returns to clients.

	ISO unless the site has said otherwise. Read per call rather than cached
	with the Policy, because it is one cached-value lookup and keeping it out of
	the Policy keeps that dataclass about permissions only.
	"""

	return DMY if _value("date_format") == "DD-MM-YYYY" else ISO


def log_payloads() -> bool:
	return bool(_value("log_payloads"))


def retention_days() -> int:
	return max(1, _int(_value("log_retention_days"), DEFAULT_RETENTION_DAYS))


def _value(fieldname):
	try:
		return frappe.get_cached_value(SETTINGS_DOCTYPE, SETTINGS_DOCTYPE, fieldname)
	except Exception:
		return None


def _int(value, fallback: int) -> int:
	try:
		value = int(value)
	except (TypeError, ValueError):
		return fallback

	return value or fallback
