"""Rules test for the Synapse access model.

Pure stdlib — policy.py imports nothing from frappe, so this runs under plain
pytest as well as `bench run-tests --app synapse`. If a case here starts
failing, a gate got looser, not the test.

The model: access is the union of the caller's Synapse Profiles, resolved by
settings.py into Policy.grants (a DocType → actions map) and Policy.full_access.
The site backstop — Policy.denied plus the built-in ALWAYS_DENIED and
ALWAYS_READ_ONLY sets — is subtractive and overrides any grant.
"""

import unittest

from synapse.mcp_tools.policy import (
	CANCEL,
	DELETE,
	OPERATE,
	READ,
	SUBMIT,
	WRITE,
	Denied,
	Policy,
	actions_possible,
	check,
)

ALL_ACTIONS = (READ, WRITE, SUBMIT, CANCEL, DELETE, OPERATE)


def policy(**overrides) -> Policy:
	"""A working policy, so each test can loosen exactly one thing.

	Task is granted everything, Sales Invoice read only — the union a caller's
	profiles would have resolved to.
	"""

	base = {
		"enabled": True,
		"read_enabled": True,
		"write_enabled": True,
		"grants": {
			"task": frozenset(ALL_ACTIONS),
			"sales invoice": frozenset({READ}),
		},
		"grant_names": {"task": "Task", "sales invoice": "Sales Invoice"},
	}
	base.update(overrides)
	return Policy(**base)


class TestMasterSwitches(unittest.TestCase):
	def test_disabled_refuses_everything(self):
		for action in ALL_ACTIONS:
			with self.subTest(action=action), self.assertRaises(Denied):
				check(policy(enabled=False), action, "Task")

	def test_read_switch_only_affects_reads(self):
		p = policy(read_enabled=False)

		with self.assertRaises(Denied):
			check(p, READ, "Task")

		self.assertEqual(check(p, WRITE, "Task"), "Task")

	def test_write_switch_affects_every_write_class_action(self):
		p = policy(write_enabled=False)

		self.assertEqual(check(p, READ, "Task"), "Task")

		for action in (WRITE, SUBMIT, CANCEL, DELETE, OPERATE):
			with self.subTest(action=action), self.assertRaises(Denied):
				check(p, action, "Task")


class TestGrants(unittest.TestCase):
	def test_ungranted_doctype_is_refused(self):
		with self.assertRaises(Denied) as ctx:
			check(policy(), READ, "Salary Slip")
		self.assertIn("profile", str(ctx.exception).lower())

	def test_action_not_granted_is_refused(self):
		# Sales Invoice is read-only in the fixture.
		self.assertEqual(check(policy(), READ, "Sales Invoice"), "Sales Invoice")

		with self.assertRaises(Denied):
			check(policy(), WRITE, "Sales Invoice")

	def test_empty_grants_permit_nothing(self):
		with self.assertRaises(Denied):
			check(policy(grants={}, grant_names={}), READ, "Task")

	def test_doctype_match_is_case_insensitive(self):
		self.assertEqual(check(policy(), READ, "task"), "task")
		self.assertEqual(check(policy(), READ, "  SALES INVOICE "), "  SALES INVOICE ")

	def test_operate_is_a_grantable_action(self):
		self.assertEqual(check(policy(), OPERATE, "Task"), "Task")

		p = policy(grants={"task": frozenset({READ})}, grant_names={"task": "Task"})
		with self.assertRaises(Denied):
			check(p, OPERATE, "Task")

	def test_missing_doctype_is_refused(self):
		for value in ("", None, 7):
			with self.subTest(value=value), self.assertRaises(Denied):
				check(policy(), READ, value)


def full(**overrides) -> Policy:
	"""A full-access policy: every DocType reachable, subject to the backstop."""

	base = {
		"enabled": True,
		"read_enabled": True,
		"write_enabled": True,
		"full_access": True,
	}
	base.update(overrides)
	return Policy(**base)


class TestFullAccess(unittest.TestCase):
	def test_any_doctype_is_reachable(self):
		for action in ALL_ACTIONS:
			with self.subTest(action=action):
				self.assertEqual(check(full(), action, "Whatever"), "Whatever")

	def test_switches_still_apply(self):
		with self.assertRaises(Denied):
			check(full(enabled=False), READ, "Task")

		with self.assertRaises(Denied):
			check(full(write_enabled=False), WRITE, "Task")

	def test_backstop_still_applies_under_full_access(self):
		p = full(denied={"salary slip": frozenset({WRITE, SUBMIT, CANCEL, DELETE, OPERATE})})
		self.assertEqual(check(p, READ, "Salary Slip"), "Salary Slip")
		with self.assertRaises(Denied):
			check(p, WRITE, "Salary Slip")


class TestBackstop(unittest.TestCase):
	def test_denied_row_overrides_a_grant(self):
		p = policy(denied={"task": frozenset({WRITE, SUBMIT, CANCEL, DELETE, OPERATE})})
		self.assertEqual(check(p, READ, "Task"), "Task")
		for action in (WRITE, SUBMIT, CANCEL, DELETE, OPERATE):
			with self.subTest(action=action), self.assertRaises(Denied) as ctx:
				check(p, action, "Task")
			self.assertIn("backstop", str(ctx.exception).lower())

	def test_denied_cannot_be_bypassed_with_capitalisation(self):
		"""The bypass that would matter. Not a convenience — a requirement."""

		p = full(denied={"salary slip": frozenset(ALL_ACTIONS)})
		for spelling in ("salary slip", "SALARY SLIP", "  Salary Slip  ", "sAlArY sLiP"):
			with self.subTest(spelling=spelling), self.assertRaises(Denied):
				check(p, READ, spelling)


class TestBuiltInBackstop(unittest.TestCase):
	"""The sets policy.py enforces whether or not a site lists them.

	Under full access a DocType arrives reachable, so anything that must never be
	reachable cannot depend on someone remembering to add a row.
	"""

	def test_credential_doctypes_are_blocked_outright(self):
		p = full()
		for name in ("OAuth Bearer Token", "oauth client", "Token Cache", "Social Login Key",
					 "Connected App", "Email Account", "Access Log"):
			for action in (READ, WRITE, DELETE, OPERATE):
				with self.subTest(doctype=name, action=action), self.assertRaises(Denied):
					check(p, action, name)

	def test_control_plane_doctypes_are_blocked_outright(self):
		# An agent must never edit the gate that governs it, even under full access.
		p = full()
		for name in ("Synapse Settings", "synapse profile", "Synapse Doctype Access",
					 "Synapse Denied DocType", "Synapse Profile Role", "Synapse Log"):
			for action in (READ, WRITE, DELETE, OPERATE):
				with self.subTest(doctype=name, action=action), self.assertRaises(Denied):
					check(p, action, name)

	def test_schema_and_permission_doctypes_are_read_only(self):
		p = full()
		for name in ("DocType", "Custom Field", "Custom DocPerm", "Server Script", "Role", "User",
					 "Property Setter", "System Settings"):
			with self.subTest(doctype=name):
				self.assertEqual(check(p, READ, name), name)

				for action in (WRITE, DELETE, OPERATE):
					with self.assertRaises(Denied):
						check(p, action, name)

	def test_read_only_set_blocks_operate(self):
		# operate is a write-class action, so it is blocked on read-only DocTypes.
		with self.assertRaises(Denied):
			check(full(), OPERATE, "Server Script")


class TestActionsPossible(unittest.TestCase):
	def test_reflects_switches(self):
		self.assertEqual(actions_possible(full()), ALL_ACTIONS)
		self.assertEqual(actions_possible(full(write_enabled=False)), (READ,))
		self.assertEqual(actions_possible(full(enabled=False)), ())
		self.assertEqual(actions_possible(full(read_enabled=False)), (WRITE, SUBMIT, CANCEL, DELETE, OPERATE))


class TestFailClosed(unittest.TestCase):
	def test_default_policy_permits_nothing(self):
		for action in ALL_ACTIONS:
			with self.subTest(action=action), self.assertRaises(Denied):
				check(Policy(), action, "Task")

	def test_default_policy_is_not_full_access(self):
		self.assertFalse(Policy().full_access)

	def test_unknown_action_is_refused(self):
		with self.assertRaises(Denied):
			check(policy(), "rename", "Task")


if __name__ == "__main__":
	unittest.main()
