"""Rules test for the MCP allowlist.

Pure stdlib — policy.py imports nothing from frappe, so this runs under plain
pytest as well as `bench run-tests --app synapse`. If a case here starts
failing, a gate got looser, not the test.
"""

import unittest

from synapse.mcp_tools.policy import (
	ALLOWLIST,
	CANCEL,
	DELETE,
	DENYLIST,
	READ,
	SUBMIT,
	WRITE,
	Denied,
	DocTypeRule,
	Policy,
	actions_possible,
	check,
)

FULL_RULE = DocTypeRule(read=True, write=True, submit=True, cancel=True, delete=True)


def policy(**overrides) -> Policy:
	"""A working policy, so each test can loosen exactly one thing."""

	base = {
		"enabled": True,
		"read_enabled": True,
		"write_enabled": True,
		"doctypes": {"Task": FULL_RULE, "Sales Invoice": DocTypeRule(read=True)},
		"role_actions": {
			"Projects Manager": frozenset({WRITE, SUBMIT, CANCEL, DELETE}),
			"Projects User": frozenset({WRITE}),
		},
	}
	base.update(overrides)
	return Policy(**base)


class TestMasterSwitches(unittest.TestCase):
	def test_disabled_refuses_everything(self):
		for action in (READ, WRITE, SUBMIT, CANCEL, DELETE):
			with self.subTest(action=action), self.assertRaises(Denied):
				check(policy(enabled=False), action, "Task", ["Projects Manager"])

	def test_read_switch_only_affects_reads(self):
		p = policy(read_enabled=False)

		with self.assertRaises(Denied):
			check(p, READ, "Task", ["Projects Manager"])

		self.assertEqual(check(p, WRITE, "Task", ["Projects Manager"]), "Task")

	def test_write_switch_only_affects_writes(self):
		p = policy(write_enabled=False)

		self.assertEqual(check(p, READ, "Task", ["Projects Manager"]), "Task")

		for action in (WRITE, SUBMIT, CANCEL, DELETE):
			with self.subTest(action=action), self.assertRaises(Denied):
				check(p, action, "Task", ["Projects Manager"])


class TestDoctypeAllowlist(unittest.TestCase):
	def test_unlisted_doctype_is_refused(self):
		with self.assertRaises(Denied) as ctx:
			check(policy(), READ, "Salary Slip", ["Projects Manager"])
		self.assertIn("allowlist", str(ctx.exception))

	def test_action_not_ticked_is_refused(self):
		# Sales Invoice is read-only in the fixture.
		self.assertEqual(check(policy(), READ, "Sales Invoice", ["Projects Manager"]), "Sales Invoice")

		with self.assertRaises(Denied):
			check(policy(), WRITE, "Sales Invoice", ["Projects Manager"])

	def test_empty_allowlist_permits_nothing(self):
		with self.assertRaises(Denied):
			check(policy(doctypes={}), READ, "Task", ["Projects Manager"])

	def test_doctype_match_is_case_insensitive_and_canonicalised(self):
		self.assertEqual(check(policy(), READ, "task", ["Projects Manager"]), "Task")
		self.assertEqual(check(policy(), READ, "  SALES INVOICE ", ["Projects Manager"]), "Sales Invoice")

	def test_missing_doctype_is_refused(self):
		for value in ("", None, 7):
			with self.subTest(value=value), self.assertRaises(Denied):
				check(policy(), READ, value, ["Projects Manager"])


class TestRoleGrants(unittest.TestCase):
	def test_read_needs_no_granted_role(self):
		self.assertEqual(check(policy(), READ, "Task", ["Some Unrelated Role"]), "Task")

	def test_write_needs_a_granted_role(self):
		with self.assertRaises(Denied) as ctx:
			check(policy(), WRITE, "Task", ["Some Unrelated Role"])
		self.assertIn("roles", str(ctx.exception))

	def test_grant_is_per_action(self):
		# Projects User holds write but not submit, cancel or delete.
		self.assertEqual(check(policy(), WRITE, "Task", ["Projects User"]), "Task")

		for action in (SUBMIT, CANCEL, DELETE):
			with self.subTest(action=action), self.assertRaises(Denied):
				check(policy(), action, "Task", ["Projects User"])

	def test_any_one_held_role_is_enough(self):
		self.assertEqual(
			check(policy(), CANCEL, "Task", ["Projects User", "Projects Manager"]), "Task"
		)

	def test_no_roles_at_all(self):
		with self.assertRaises(Denied):
			check(policy(), WRITE, "Task", [])

		with self.assertRaises(Denied):
			check(policy(), WRITE, "Task", None)

	def test_empty_role_table_makes_endpoint_read_only(self):
		p = policy(role_actions={})

		self.assertEqual(check(p, READ, "Task", ["Projects Manager"]), "Task")

		for action in (WRITE, SUBMIT, CANCEL, DELETE):
			with self.subTest(action=action), self.assertRaises(Denied):
				check(p, action, "Task", ["Projects Manager"])


def denylist(**overrides) -> Policy:
	"""A denylist policy: everything reachable except what is listed."""

	base = {
		"enabled": True,
		"read_enabled": True,
		"write_enabled": True,
		"mode": DENYLIST,
		"denied": {
			"Salary Slip": frozenset({READ, WRITE, SUBMIT, CANCEL, DELETE}),
			"Sales Invoice": frozenset({WRITE, SUBMIT, CANCEL, DELETE}),
		},
		"role_actions": {
			"Projects Manager": frozenset({WRITE, SUBMIT, CANCEL, DELETE}),
		},
	}
	base.update(overrides)
	return Policy(**base)


class TestDenylistMode(unittest.TestCase):
	def test_unlisted_doctype_is_reachable(self):
		p = denylist()
		self.assertEqual(check(p, READ, "Task", ["Projects Manager"]), "Task")
		self.assertEqual(check(p, WRITE, "Task", ["Projects Manager"]), "Task")

	def test_unknown_doctype_is_passed_through_unchanged(self):
		# Whether the DocType exists is Frappe's business, not the policy's; the
		# caller resolves the name before it gets here.
		self.assertEqual(check(denylist(), READ, "Whatever", ["Projects Manager"]), "Whatever")

	def test_listed_doctype_is_blocked(self):
		for action in (READ, WRITE, SUBMIT, CANCEL, DELETE):
			with self.subTest(action=action), self.assertRaises(Denied) as ctx:
				check(denylist(), action, "Salary Slip", ["Projects Manager"])
			self.assertIn("denylist", str(ctx.exception))

	def test_partial_block_leaves_reads_working(self):
		# Sales Invoice blocks every write but not read.
		self.assertEqual(check(denylist(), READ, "Sales Invoice", ["Projects Manager"]), "Sales Invoice")

		for action in (WRITE, SUBMIT, CANCEL, DELETE):
			with self.subTest(action=action), self.assertRaises(Denied):
				check(denylist(), action, "Sales Invoice", ["Projects Manager"])

	def test_block_cannot_be_bypassed_with_different_capitalisation(self):
		"""The bypass that would matter. Not a convenience — a requirement."""

		for spelling in ("salary slip", "SALARY SLIP", "  Salary Slip  ", "sAlArY sLiP"):
			with self.subTest(spelling=spelling), self.assertRaises(Denied):
				check(denylist(), READ, spelling, ["Projects Manager"])

	def test_writes_still_need_a_granted_role(self):
		with self.assertRaises(Denied) as ctx:
			check(denylist(), WRITE, "Task", ["Some Unrelated Role"])
		self.assertIn("roles", str(ctx.exception))

	def test_switches_still_apply(self):
		with self.assertRaises(Denied):
			check(denylist(enabled=False), READ, "Task", ["Projects Manager"])

		with self.assertRaises(Denied):
			check(denylist(write_enabled=False), WRITE, "Task", ["Projects Manager"])

	def test_allowlist_table_is_ignored_in_denylist_mode(self):
		# An allowlist left over from before the switch must not narrow anything.
		p = denylist(doctypes={"Only This": FULL_RULE})
		self.assertEqual(check(p, READ, "Task", ["Projects Manager"]), "Task")


class TestDenylistBuiltIns(unittest.TestCase):
	"""The sets policy.py enforces whether or not a site lists them.

	These matter more in denylist mode than anywhere else: a new DocType arrives
	reachable, so anything that must never be reachable cannot depend on someone
	remembering to add a row.
	"""

	def test_credential_doctypes_are_blocked_outright(self):
		p = denylist(denied={})
		for name in ("OAuth Bearer Token", "oauth client", "Token Cache", "Social Login Key",
					 "Connected App", "Email Account", "Access Log"):
			for action in (READ, WRITE, DELETE):
				with self.subTest(doctype=name, action=action), self.assertRaises(Denied):
					check(p, action, name, ["Projects Manager"])

	def test_control_plane_doctypes_are_blocked_outright(self):
		# An agent must never edit the gate that governs it, even as System Manager.
		p = denylist(denied={})
		for name in ("MCP Settings", "mcp allowed doctype", "MCP Denied DocType",
					 "MCP Role Permission", "MCP Access Log"):
			for action in (READ, WRITE, DELETE):
				with self.subTest(doctype=name, action=action), self.assertRaises(Denied):
					check(p, action, name, ["Projects Manager"])

	def test_schema_and_permission_doctypes_are_read_only(self):
		p = denylist(denied={})
		for name in ("DocType", "Custom Field", "Custom DocPerm", "Server Script", "Role", "User",
					 "Property Setter", "System Settings"):
			with self.subTest(doctype=name):
				self.assertEqual(check(p, READ, name, ["Projects Manager"]), name)

				for action in (WRITE, DELETE):
					with self.assertRaises(Denied):
						check(p, action, name, ["Projects Manager"])

	def test_built_ins_do_not_apply_in_allowlist_mode(self):
		# In allowlist mode the table is the only authority; a site that
		# deliberately lists Custom Field for write gets what it asked for.
		p = policy(doctypes={"Custom Field": FULL_RULE})
		self.assertEqual(check(p, WRITE, "Custom Field", ["Projects Manager"]), "Custom Field")


class TestActionsPossible(unittest.TestCase):
	def test_reflects_switches_and_roles(self):
		self.assertEqual(
			actions_possible(denylist(), ["Projects Manager"]),
			(READ, WRITE, SUBMIT, CANCEL, DELETE),
		)
		self.assertEqual(actions_possible(denylist(), ["Nobody"]), (READ,))
		self.assertEqual(actions_possible(denylist(write_enabled=False), ["Projects Manager"]), (READ,))
		self.assertEqual(actions_possible(denylist(enabled=False), ["Projects Manager"]), ())

	def test_partial_role_grant(self):
		p = denylist(role_actions={"Projects User": frozenset({WRITE})})
		self.assertEqual(actions_possible(p, ["Projects User"]), (READ, WRITE))


class TestFailClosed(unittest.TestCase):
	def test_default_mode_is_allowlist(self):
		self.assertEqual(Policy().mode, ALLOWLIST)

	def test_default_policy_permits_nothing(self):
		for action in (READ, WRITE, SUBMIT, CANCEL, DELETE):
			with self.subTest(action=action), self.assertRaises(Denied):
				check(Policy(), action, "Task", ["System Manager"])

	def test_unknown_action_is_refused(self):
		with self.assertRaises(Denied):
			check(policy(), "rename", "Task", ["Projects Manager"])


if __name__ == "__main__":
	unittest.main()
