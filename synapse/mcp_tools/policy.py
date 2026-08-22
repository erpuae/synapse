# Copyright (c) 2026, Dxbitz and contributors
"""The MCP access list: which DocTypes may be touched, and by which roles.

Pure stdlib — no frappe import, no I/O — so every rule is unit testable without
a site. settings.py builds a Policy from the MCP Settings DocType and hands it
here. See tests/test_mcp_policy.py.

This is one of four gates a write passes through:

1. The endpoint itself is authenticated (OAuth bearer or session).
2. The tool declares a role — mcp_core refuses and hides it otherwise.
3. **This module** — the DocType is reachable for that action, and the caller
   holds a role the site has granted that action to.
4. Frappe's own permission check, because every tool operates as the session
   user with permissions on. DocType permissions, User Permissions, share rules
   and submit/cancel rights all still apply.

Gate 3 runs in one of two modes, set per site in MCP Settings:

* **Allowlist** — nothing is reachable except the DocTypes listed. Fails closed,
  and a new DocType on the site is unreachable until someone says otherwise.
* **Denylist** — everything is reachable except the DocTypes listed. The narrower
  boundary then becomes the user's own Frappe permissions, with this list
  carving out the things no agent should touch whatever its user may do.

Denylist is the easier one to live with on a full ERP; it is also the one where a
new DocType arrives reachable, so the two built-in sets below matter more there.
They apply in denylist mode whether or not anyone remembers to list them.
"""

from dataclasses import dataclass, field

__all__ = [
	"ACTIONS",
	"ALLOWLIST",
	"ALWAYS_DENIED",
	"ALWAYS_READ_ONLY",
	"CANCEL",
	"DELETE",
	"DENYLIST",
	"Denied",
	"DocTypeRule",
	"MODES",
	"Policy",
	"READ",
	"SUBMIT",
	"WRITE",
	"actions_possible",
	"check",
]

READ = "read"
WRITE = "write"
SUBMIT = "submit"
CANCEL = "cancel"
DELETE = "delete"

ACTIONS = (READ, WRITE, SUBMIT, CANCEL, DELETE)

# Everything except a plain read needs a role the site has granted the action to.
WRITE_ACTIONS = (WRITE, SUBMIT, CANCEL, DELETE)

ALLOWLIST = "Allowlist"
DENYLIST = "Denylist"
MODES = (ALLOWLIST, DENYLIST)

# Never reachable in denylist mode, for any action, listed or not. Tokens,
# credentials and the plumbing that hands them out — reading these is how a
# reader becomes a writer. Mirrors guard.BLOCKED_TABLES, which does the same job
# for the raw SQL tool. Compared case insensitively.
ALWAYS_DENIED = frozenset(
	{
		"oauth bearer token",
		"oauth authorization code",
		"oauth client",
		"token cache",
		"social login key",
		"connected app",
		"webhook",
		"email account",
		"integration request",
		"user social login",
		"access log",
	}
)

# Readable but never writable in denylist mode. Writing to these is not data
# entry, it is changing the schema, the code or the permission model — and an
# agent that can edit Custom DocPerm can grant itself anything.
ALWAYS_READ_ONLY = frozenset(
	{
		"doctype",
		"docfield",
		"docperm",
		"custom docperm",
		"custom field",
		"property setter",
		"server script",
		"client script",
		"print format",
		"report",
		"role",
		"has role",
		"user",
		"user permission",
		"system settings",
		"workflow",
		"scheduled job type",
	}
)


class Denied(Exception):
	"""Raised when gate 3 refuses an operation.

	The message names the gate that closed. It goes straight back to the model,
	which needs to know whether to give up or try a different DocType.
	"""


@dataclass(frozen=True)
class DocTypeRule:
	"""What the site permits on one DocType through MCP.

	In allowlist rows a true flag *grants* the action. In denylist rows a true
	flag *blocks* it — see Policy.denied, which stores the blocked action names
	rather than reusing this class, so the two can never be confused.
	"""

	read: bool = False
	write: bool = False
	submit: bool = False
	cancel: bool = False
	delete: bool = False

	def allows(self, action: str) -> bool:
		return bool(getattr(self, action, False))


@dataclass(frozen=True)
class Policy:
	"""A snapshot of MCP Settings, in a form that needs no database."""

	enabled: bool = False
	read_enabled: bool = False
	write_enabled: bool = False
	mode: str = ALLOWLIST
	doctypes: dict[str, DocTypeRule] = field(default_factory=dict)
	denied: dict[str, frozenset] = field(default_factory=dict)
	role_actions: dict[str, frozenset] = field(default_factory=dict)

	def rule_for(self, doctype: str) -> DocTypeRule | None:
		"""The allowlist row for a DocType. Exact match first, then case-insensitive."""

		if doctype in self.doctypes:
			return self.doctypes[doctype]

		wanted = _norm(doctype)
		for name, rule in self.doctypes.items():
			if _norm(name) == wanted:
				return rule

		return None

	def blocked_actions(self, doctype: str) -> frozenset:
		"""Every action the denylist blocks on a DocType, built-ins included.

		Matching is case insensitive throughout. That is not a convenience here
		the way it is on the allowlist — a denylist that only matched exact
		capitalisation would be bypassed by asking for 'salary slip'.
		"""

		wanted = _norm(doctype)
		blocked = set()

		for name, actions in self.denied.items():
			if _norm(name) == wanted:
				blocked |= set(actions)

		if wanted in ALWAYS_DENIED:
			blocked |= set(ACTIONS)

		if wanted in ALWAYS_READ_ONLY:
			blocked |= set(WRITE_ACTIONS)

		return frozenset(blocked)

	def resolve_name(self, doctype: str) -> str:
		"""Return the allowlist's spelling of a DocType, for use against the db."""

		wanted = _norm(doctype)
		for name in self.doctypes:
			if _norm(name) == wanted:
				return name

		return doctype


def check(policy: Policy, action: str, doctype: str, user_roles) -> str:
	"""Return the canonical DocType name, or raise Denied naming the gate.

	Args:
		policy: The site's current MCP Settings.
		action: One of ACTIONS.
		doctype: The target DocType. Callers pass the name Frappe resolved, so
			capitalisation is already canonical; matching here is still case
			insensitive rather than trusting that.
		user_roles: The calling user's roles.
	"""

	if action not in ACTIONS:
		raise Denied(f"Unknown action '{action}'.")

	if not policy.enabled:
		raise Denied("MCP access is switched off for this site (MCP Settings).")

	if action == READ and not policy.read_enabled:
		raise Denied("MCP read tools are switched off for this site (MCP Settings).")

	if action != READ and not policy.write_enabled:
		raise Denied("MCP write tools are switched off for this site (MCP Settings).")

	if not doctype or not isinstance(doctype, str):
		raise Denied("A DocType is required.")

	resolved = _check_list(policy, action, doctype)

	if action in WRITE_ACTIONS and not _role_grants(policy, action, user_roles):
		raise Denied(
			f"None of your roles are granted '{action}' through MCP. "
			"A System Manager grants this per role in MCP Settings."
		)

	return resolved


def actions_possible(policy: Policy, user_roles) -> tuple:
	"""The actions the switches and role grants allow, ignoring any DocType.

	Used by list_available_doctypes in denylist mode, where enumerating every
	reachable DocType would mean returning the site's whole schema.
	"""

	possible = []

	for action in ACTIONS:
		if not policy.enabled:
			break

		if action == READ and not policy.read_enabled:
			continue

		if action != READ and not policy.write_enabled:
			continue

		if action in WRITE_ACTIONS and not _role_grants(policy, action, user_roles):
			continue

		possible.append(action)

	return tuple(possible)


def _check_list(policy: Policy, action: str, doctype: str) -> str:
	"""The mode-specific half of gate 3."""

	if policy.mode == DENYLIST:
		if action in policy.blocked_actions(doctype):
			raise Denied(
				f"'{doctype}' is blocked for '{action}' by this site's MCP denylist."
			)
		return doctype

	# Allowlist. Anything not listed is refused, which is the whole point.
	rule = policy.rule_for(doctype)
	if rule is None:
		raise Denied(
			f"'{doctype}' is not on the MCP allowlist. "
			"Only DocTypes listed in MCP Settings can be reached through this endpoint."
		)

	if not rule.allows(action):
		raise Denied(f"The MCP allowlist does not permit '{action}' on '{doctype}'.")

	return policy.resolve_name(doctype)


def _role_grants(policy: Policy, action: str, user_roles) -> bool:
	return any(action in policy.role_actions.get(role, frozenset()) for role in (user_roles or ()))


def _norm(value) -> str:
	return str(value or "").strip().lower()
