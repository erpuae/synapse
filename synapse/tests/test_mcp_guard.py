"""Rules test for the MCP read-only SQL guard.

Pure stdlib — guard.py imports nothing from frappe, so this runs under plain
pytest as well as `bench run-tests --app synapse`. If a case here starts
failing, the guard got looser, not the test.
"""

import unittest

from synapse.mcp_tools.guard import MAX_QUERY_LENGTH, UnsafeQuery, validate_read_only

REJECTED = [
	("write statement", "DELETE FROM tabUser"),
	("write statement", "UPDATE tabItem SET item_name = 'x'"),
	("stacked statement", "SELECT 1; DROP TABLE tabUser"),
	("line comment", "SELECT * FROM tabUser -- comment"),
	("block comment", "SELECT * FROM tabUser /* comment */"),
	("hash comment", "SELECT * FROM tabUser # comment"),
	("secrets table", "SELECT * FROM __Auth"),
	("file write", "SELECT * FROM tabUser INTO OUTFILE '/tmp/x'"),
	("time based probe", "SELECT SLEEP(30)"),
	("session variable", "SET SESSION max_statement_time = 1"),
	("token table", "SELECT * FROM `tabOAuth Bearer Token`"),
	("token table, mixed case", "select name from `taboauth authorization code`"),
	# Derived from policy.ALWAYS_DENIED — these used to slip through the SQL tool.
	("oauth client secret", "SELECT client_id, client_secret FROM `tabOAuth Client`"),
	("user social login", "SELECT * FROM `tabUser Social Login`"),
	("control plane", "SELECT * FROM `tabMCP Settings`"),
	("audit trail", "SELECT * FROM `tabMCP Access Log`"),
	# Named-lock timing functions — underscore defeats the bare `lock` boundary.
	("get_lock", "SELECT GET_LOCK('x', 10)"),
	("release_lock", "SELECT RELEASE_LOCK('x')"),
	("is_free_lock", "SELECT IS_FREE_LOCK('x')"),
	("empty", "   "),
	("not a string", None),
]

ACCEPTED = [
	"SELECT name FROM tabCompany",
	"SELECT name, grand_total FROM `tabSales Invoice` WHERE docstatus = 1 LIMIT 10",
	"WITH x AS (SELECT name FROM tabCustomer) SELECT * FROM x",
	"  ((SELECT 1))  ",
	"SELECT name FROM tabCompany;",
]


class TestGuardRejects(unittest.TestCase):
	def test_rejected_queries(self):
		for label, query in REJECTED:
			with self.subTest(case=label):
				with self.assertRaises(UnsafeQuery):
					validate_read_only(query)

	def test_over_length_is_rejected(self):
		query = "SELECT name FROM tabCompany WHERE name != '" + ("a" * MAX_QUERY_LENGTH) + "'"
		with self.assertRaises(UnsafeQuery):
			validate_read_only(query)

	def test_extra_blocked_tables_from_site_config(self):
		query = "SELECT name FROM `tabSalary Slip`"
		validate_read_only(query)  # allowed by default

		with self.assertRaises(UnsafeQuery):
			validate_read_only(query, extra_blocked_tables=["tabSalary Slip"])

	def test_error_names_the_rule(self):
		with self.assertRaises(UnsafeQuery) as ctx:
			validate_read_only("SELECT * FROM tabUser -- x")
		self.assertIn("comment", str(ctx.exception).lower())

		with self.assertRaises(UnsafeQuery) as ctx:
			validate_read_only("DELETE FROM tabUser")
		self.assertIn("statement type", str(ctx.exception).lower())


class TestGuardAccepts(unittest.TestCase):
	def test_accepted_queries(self):
		for query in ACCEPTED:
			with self.subTest(query=query):
				validate_read_only(query)

	def test_returns_normalised_query(self):
		self.assertEqual(validate_read_only("  SELECT 1 ;  "), "SELECT 1")
		self.assertEqual(validate_read_only("SELECT 1"), "SELECT 1")


if __name__ == "__main__":
	unittest.main()
