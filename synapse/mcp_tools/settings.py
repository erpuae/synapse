# Copyright (c) 2026, Dxbitz and contributors
"""Builds the request's Policy from Synapse Settings and the caller's profiles.

The Policy is user-scoped: a call's reach is the union of every enabled Synapse
Profile whose roles the calling user holds. That is resolved here, once, and
cached on frappe.local for the life of the request, a request is one user, so
the cache is safe, and it saves rebuilding the union on every tool call in a
multi-call request.
"""

import frappe

from synapse.mcp_tools.policy import ACTIONS, Policy
from synapse.mcp_tools.serialise import DMY, ISO, Formats

SETTINGS_DOCTYPE = "Synapse Settings"
PROFILE_DOCTYPE = "Synapse Profile"
CACHE_KEY = "_synapse_policy"

# The site can lower these in Synapse Settings but never raise them past here.
HARD_ROW_CAP = 500
DEFAULT_ROW_LIMIT = 100
DEFAULT_RETENTION_DAYS = 90


def get_policy() -> Policy:
	"""Return this request's Policy, building it once for the current user."""

	cached = getattr(frappe.local, CACHE_KEY, None)
	if cached is not None:
		return cached

	policy = _build()
	setattr(frappe.local, CACHE_KEY, policy)
	return policy


def clear_cache():
	"""Called from Synapse Settings/Profile on_update so an edit takes effect at once."""

	if hasattr(frappe.local, CACHE_KEY):
		delattr(frappe.local, CACHE_KEY)


def _build() -> Policy:
	try:
		doc = frappe.get_cached_doc(SETTINGS_DOCTYPE)
	except Exception:
		# Not migrated yet, or the DocType is gone. Deny everything rather than
		# defaulting open.
		return Policy()

	denied = {}
	for row in doc.get("denied_doctypes") or []:
		if not row.document_type:
			continue

		blocked = {action for action in ACTIONS if row.get(f"deny_{action}")}
		if blocked:
			denied[_norm(row.document_type)] = frozenset(blocked)

	full_access, sql_access, grants, grant_names = _resolve_profiles()

	return Policy(
		enabled=bool(doc.enabled),
		read_enabled=bool(doc.enable_read_tools),
		write_enabled=bool(doc.enable_write_tools),
		sql_enabled=bool(doc.enable_sql_tool) and sql_access,
		full_access=full_access,
		grants=grants,
		grant_names=grant_names,
		denied=denied,
	)


def _resolve_profiles() -> tuple:
	"""Union the enabled profiles whose roles the current user holds.

	Returns (full_access, sql_access, grants, grant_names). `grants` maps a
	normalised DocType name to the set of actions granted across those profiles;
	`grant_names` keeps a display spelling for each. Full Access short-circuits
	the grid, the grants map is left empty because policy.granted_actions treats
	full_access as "every action on every DocType".
	"""

	roles = set(frappe.get_roles(frappe.session.user))

	full_access = False
	sql_access = False
	grants: dict[str, set] = {}
	grant_names: dict[str, str] = {}

	names = frappe.get_all(PROFILE_DOCTYPE, filters={"enabled": 1}, pluck="name")
	for name in names:
		profile = frappe.get_cached_doc(PROFILE_DOCTYPE, name)

		profile_roles = {row.role for row in profile.get("roles") or [] if row.role}
		if not (profile_roles & roles):
			continue

		if profile.allow_sql:
			sql_access = True

		if profile.full_access:
			full_access = True
			continue

		for row in profile.get("doctype_access") or []:
			if not row.document_type:
				continue

			actions = {action for action in ACTIONS if row.get(f"allow_{action}")}
			if not actions:
				continue

			key = _norm(row.document_type)
			grants.setdefault(key, set()).update(actions)
			grant_names.setdefault(key, row.document_type)

	frozen = {key: frozenset(actions) for key, actions in grants.items()}
	return full_access, sql_access, frozen, grant_names


# ── predicates used as `enabled=` on tool registrations ───────────────────────
def read_tools_enabled() -> bool:
	"""Read tools are visible when reads are on and the caller has some grant.

	A user with no matching profile sees no document tools rather than a listing
	full of tools that would all refuse.
	"""

	policy = get_policy()
	return policy.enabled and policy.read_enabled and _has_any_grant(policy)


def write_tools_enabled() -> bool:
	policy = get_policy()
	return policy.enabled and policy.write_enabled and _has_write_grant(policy)


def operate_tools_enabled() -> bool:
	"""run_operation is visible only when the caller holds an 'operate' grant.

	It shares the write master switch, operate is a write-class action, but it
	is hidden from callers with no operate grant so the powerful tool never even
	appears for a user who could not use it.
	"""

	policy = get_policy()
	if not (policy.enabled and policy.write_enabled):
		return False

	if policy.full_access:
		return True

	return any("operate" in actions for actions in policy.grants.values())


def sql_tool_enabled() -> bool:
	policy = get_policy()
	return policy.enabled and policy.sql_enabled


def _has_any_grant(policy: Policy) -> bool:
	return bool(policy.full_access or policy.grants)


def _has_write_grant(policy: Policy) -> bool:
	if policy.full_access:
		return True

	return any(action != "read" for actions in policy.grants.values() for action in actions)


# ── numeric and display settings ──────────────────────────────────────────────
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


def model_provider() -> str:
	"""The model family the site presents Synapse for. Showcase only, no behaviour."""

	return _value("model_provider") or "Claude"


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


def _norm(value) -> str:
	return str(value or "").strip().lower()
