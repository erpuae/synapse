# Copyright (c) 2026, Dxbitz and contributors
"""The Synapse access model: which DocTypes may be touched, and how.

Pure stdlib, no frappe import, no I/O, so every rule is unit testable without
a site. settings.py builds a Policy from the calling user's Synapse Profiles and
the site's Synapse Settings, and hands it here. See tests/test_mcp_policy.py.

Access is granted by **Synapse Profile** records. A user's reach is the union of
every enabled profile whose roles they hold, each profile's DocType Access
grid, or everything if the profile has Full Access. That union is precomputed
per request into Policy.grants (and Policy.full_access), so the check here needs
no roles: it is a lookup against the grant the user already resolved to.

This is one of three gates a call passes through:

1. The endpoint is authenticated (OAuth bearer, API key or session), an
   unauthenticated POST is refused by the framework before any tool runs.
2. **This module**, the action is granted for the DocType by the caller's
   profiles, and is not taken back by the site backstop below.
3. Frappe's own permission check, because every tool operates as the session
   user with permissions on. DocType permissions, User Permissions, share rules
   and submit/cancel rights all still apply.

The backstop is subtractive and always wins over a profile grant:

* **Blocked DocTypes** listed in Synapse Settings, carve-outs no agent may
  touch whatever its profiles allow.
* **ALWAYS_DENIED**, never reachable, for any action, listed or not. Tokens,
  credentials and the plumbing that hands them out, plus Synapse's own control
  plane, so an agent can never rewrite the gate that governs it.
* **ALWAYS_READ_ONLY**, readable but never writable. Writing to these is
  changing the schema, the code or the permission model, not entering data.
"""

from dataclasses import dataclass, field

__all__ = [
	"ACTIONS",
	"ALWAYS_DENIED",
	"ALWAYS_READ_ONLY",
	"CANCEL",
	"DELETE",
	"Denied",
	"OPERATE",
	"Policy",
	"READ",
	"SUBMIT",
	"WRITE",
	"WRITE_ACTIONS",
	"actions_possible",
	"check",
]

READ = "read"
WRITE = "write"
SUBMIT = "submit"
CANCEL = "cancel"
DELETE = "delete"
OPERATE = "operate"

ACTIONS = (READ, WRITE, SUBMIT, CANCEL, DELETE, OPERATE)

# Everything except a plain read is a write-class action: it needs the write
# switch on, and it is what ALWAYS_READ_ONLY blocks. `operate` runs a
# document's own method, which can change anything the method changes, so it
# belongs here.
WRITE_ACTIONS = (WRITE, SUBMIT, CANCEL, DELETE, OPERATE)

# Never reachable, for any action, listed or not. Tokens, credentials and the
# plumbing that hands them out, reading these is how a reader becomes a writer -
# plus Synapse's own control plane, so an agent can never rewrite the gate that
# governs it. guard.BLOCKED_TABLES is derived from this set (see guard.py) so the
# raw SQL tool blocks the same tables and the two can never drift. Compared case
# insensitively.
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
		# Synapse's control plane. Blocking it here stops an agent whose user is
		# a System Manager from editing the gate through the write tools.
		"synapse settings",
		"synapse profile",
		"synapse profile role",
		"synapse profile tool",
		"synapse doctype access",
		"synapse denied doctype",
		"synapse log",
	}
)

# Readable but never writable. Writing to these is not data entry, it is changing
# the schema, the code or the permission model, and an agent that can edit
# Custom DocPerm can grant itself anything.
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
		# Synapse's own read-layer catalog. Agents may read it, never rewrite it.
		"synapse component",
	}
)


class Denied(Exception):
	"""Raised when the access gate refuses an operation.

	The message names the gate that closed. It goes straight back to the model,
	which needs to know whether to give up or try a different DocType.
	"""


@dataclass(frozen=True)
class Policy:
	"""A snapshot of the caller's resolved access, in a form that needs no database.

	`grants` and `full_access` are the union across the caller's enabled Synapse
	Profiles; `denied` is the site backstop. Keys in `grants` and `denied` are
	normalised (stripped, lower-cased); matching here is case insensitive
	throughout, a grant that only matched exact capitalisation would be bypassed
	by asking for 'salary slip'.
	"""

	enabled: bool = False
	read_enabled: bool = False
	write_enabled: bool = False
	sql_enabled: bool = False
	custom_enabled: bool = False
	full_access: bool = False
	grants: dict[str, frozenset] = field(default_factory=dict)
	grant_names: dict[str, str] = field(default_factory=dict)
	denied: dict[str, frozenset] = field(default_factory=dict)
	custom_tools: frozenset = field(default_factory=frozenset)

	def granted_actions(self, doctype: str) -> frozenset:
		"""Actions the caller's profiles grant on a DocType, before the backstop."""

		if self.full_access:
			return frozenset(ACTIONS)

		return self.grants.get(_norm(doctype), frozenset())

	def blocked_actions(self, doctype: str) -> frozenset:
		"""Every action the backstop blocks on a DocType, built-ins included."""

		wanted = _norm(doctype)
		blocked = set(self.denied.get(wanted, frozenset()))

		if wanted in ALWAYS_DENIED:
			blocked |= set(ACTIONS)

		if wanted in ALWAYS_READ_ONLY:
			blocked |= set(WRITE_ACTIONS)

		return frozenset(blocked)


def check(policy: Policy, action: str, doctype: str) -> str:
	"""Return the DocType name, or raise Denied naming the gate that closed.

	Args:
		policy: The caller's resolved access for this request.
		action: One of ACTIONS.
		doctype: The target DocType. Callers pass the name Frappe resolved, so
			capitalisation is already canonical; matching here is still case
			insensitive rather than trusting that.
	"""

	if action not in ACTIONS:
		raise Denied(f"Unknown action '{action}'.")

	if not policy.enabled:
		raise Denied("Synapse access is switched off for this site (Synapse Settings).")

	if action == READ and not policy.read_enabled:
		raise Denied("Synapse read tools are switched off for this site (Synapse Settings).")

	if action != READ and not policy.write_enabled:
		raise Denied("Synapse write tools are switched off for this site (Synapse Settings).")

	if not doctype or not isinstance(doctype, str):
		raise Denied("A DocType is required.")

	# Backstop first, it overrides any profile grant.
	if action in policy.blocked_actions(doctype):
		raise Denied(
			f"'{doctype}' is blocked for '{action}' by this site's Synapse backstop."
		)

	if action not in policy.granted_actions(doctype):
		raise Denied(
			f"None of your Synapse profiles grant '{action}' on '{doctype}'. "
			"A System Manager grants this in a Synapse Profile."
		)

	return doctype


def actions_possible(policy: Policy) -> tuple:
	"""The actions the switches allow at all, ignoring any DocType.

	Used by list_available_doctypes in full-access mode, where enumerating every
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

		possible.append(action)

	return tuple(possible)


def _norm(value) -> str:
	return str(value or "").strip().lower()
