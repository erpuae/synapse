"""Tests for the vendored MCP core and value conversion.

Pure stdlib, mcp_core.schema and mcp_tools.serialise import nothing from
frappe. These cover the two things a vendored library has to keep working: the
tool schemas a client is shown, and the argument checking that stands in front
of every tool body.
"""

import datetime
import decimal
import unittest

from synapse.mcp_core import MCP, ToolAnnotations
from synapse.mcp_core.schema import (
	InvalidArguments,
	build_input_schema,
	split_docstring,
	validate_arguments,
)
from synapse.mcp_tools.serialise import DMY, ISO, to_client, to_db_date


def sample(doctype: str, name: str, values: dict, limit: int = 100, filters: dict | None = None):
	"""Do a thing.

	Args:
		doctype: The DocType.
		name: The document
			name, wrapped over two lines.
		values: Field values.
	"""


class TestInputSchema(unittest.TestCase):
	def setUp(self):
		self.schema = build_input_schema(sample)

	def test_types(self):
		props = self.schema["properties"]
		self.assertEqual(props["doctype"]["type"], "string")
		self.assertEqual(props["limit"]["type"], "integer")
		self.assertEqual(props["values"]["type"], "object")

	def test_optional_collapses_to_a_type_list(self):
		self.assertEqual(self.schema["properties"]["filters"]["type"], ["object", "null"])

	def test_only_parameters_without_defaults_are_required(self):
		self.assertEqual(self.schema["required"], ["doctype", "name", "values"])

	def test_untyped_parameter_is_unconstrained(self):
		def untyped(value=None):
			pass

		self.assertEqual(build_input_schema(untyped)["properties"]["value"], {})


class TestToolRegistration(unittest.TestCase):
	"""The registry is what a client actually sees, so assert on the listing."""

	def setUp(self):
		self.mcp = MCP("test-server")
		self.mcp.tool(roles=["MCP Agent"], annotations=ToolAnnotations(readOnlyHint=True))(sample)
		self.tool = self.mcp._tools["sample"]

	def test_docstring_descriptions_land_on_the_schema(self):
		props = self.tool.as_listing()["inputSchema"]["properties"]
		self.assertEqual(props["doctype"]["description"], "The DocType.")
		# Undocumented parameters are listed, just without a description.
		self.assertNotIn("description", props["limit"])

	def test_listing_shape(self):
		listing = self.tool.as_listing()
		self.assertEqual(listing["name"], "sample")
		self.assertEqual(listing["description"], "Do a thing.")
		self.assertEqual(listing["annotations"], {"readOnlyHint": True})

	def test_roles_are_recorded_on_the_tool(self):
		self.assertEqual(self.tool.roles, ("MCP Agent",))

	def test_explicit_name_and_description_win(self):
		mcp = MCP("test-server")
		mcp.tool(name="renamed", description="Overridden.")(sample)
		self.assertEqual(mcp._tools["renamed"].description, "Overridden.")


class TestDocstring(unittest.TestCase):
	def test_summary_stops_at_args(self):
		summary, args = split_docstring(sample.__doc__)
		self.assertEqual(summary, "Do a thing.")
		self.assertEqual(set(args), {"doctype", "name", "values"})

	def test_wrapped_arg_description_is_joined(self):
		_, args = split_docstring(sample.__doc__)
		self.assertEqual(args["name"], "The document name, wrapped over two lines.")

	def test_no_docstring(self):
		self.assertEqual(split_docstring(None), ("", {}))


class TestArgumentValidation(unittest.TestCase):
	def setUp(self):
		self.schema = build_input_schema(sample)

	def test_valid_arguments_pass(self):
		args = {"doctype": "Task", "name": "TASK-1", "values": {"status": "Open"}}
		self.assertEqual(validate_arguments(args, self.schema), args)

	def test_unknown_argument_is_an_error_not_a_silent_drop(self):
		args = {"doctype": "Task", "name": "TASK-1", "values": {}, "filter": {"x": 1}}
		with self.assertRaises(InvalidArguments) as ctx:
			validate_arguments(args, self.schema)
		self.assertIn("filter", str(ctx.exception))

	def test_missing_required_argument(self):
		with self.assertRaises(InvalidArguments) as ctx:
			validate_arguments({"doctype": "Task"}, self.schema)
		self.assertIn("name", str(ctx.exception))

	def test_wrong_type(self):
		with self.assertRaises(InvalidArguments):
			validate_arguments({"doctype": "Task", "name": "T", "values": "not an object"}, self.schema)

	def test_bool_does_not_satisfy_integer(self):
		args = {"doctype": "Task", "name": "T", "values": {}, "limit": True}
		with self.assertRaises(InvalidArguments):
			validate_arguments(args, self.schema)

	def test_int_satisfies_number(self):
		def numeric(rate: float):
			pass

		validate_arguments({"rate": 5}, build_input_schema(numeric))

	def test_whole_number_float_satisfies_integer_and_is_coerced(self):
		def paged(limit: int):
			pass

		schema = build_input_schema(paged)
		out = validate_arguments({"limit": 5.0}, schema)
		self.assertEqual(out["limit"], 5)
		self.assertIsInstance(out["limit"], int)

	def test_fractional_float_still_rejected_for_integer(self):
		def paged(limit: int):
			pass

		with self.assertRaises(InvalidArguments):
			validate_arguments({"limit": 5.5}, build_input_schema(paged))

	def test_null_allowed_where_optional(self):
		args = {"doctype": "Task", "name": "T", "values": {}, "filters": None}
		validate_arguments(args, self.schema)

	def test_arguments_must_be_an_object(self):
		with self.assertRaises(InvalidArguments):
			validate_arguments(["Task"], self.schema)


class TestSerialisation(unittest.TestCase):
	def test_iso_is_the_default(self):
		self.assertEqual(to_client(datetime.date(2026, 8, 19)), "2026-08-19")
		self.assertEqual(
			to_client(datetime.datetime(2026, 8, 19, 14, 3, 5)), "2026-08-19 14:03:05"
		)

	def test_day_first_when_the_site_asks_for_it(self):
		self.assertEqual(to_client(datetime.date(2026, 8, 19), DMY), "19-08-2026")
		self.assertEqual(
			to_client(datetime.datetime(2026, 8, 19, 14, 3, 5), DMY), "19-08-2026 14:03:05"
		)

	def test_decimal_and_timedelta(self):
		self.assertEqual(to_client(decimal.Decimal("10.50")), 10.5)
		self.assertEqual(to_client(datetime.timedelta(hours=2, minutes=5, seconds=9)), "02:05:09")

	def test_nested_structures_carry_the_format_down(self):
		value = {"items": [{"date": datetime.date(2026, 1, 2)}]}
		self.assertEqual(to_client(value, ISO), {"items": [{"date": "2026-01-02"}]})
		self.assertEqual(to_client(value, DMY), {"items": [{"date": "02-01-2026"}]})

	def test_writes_accept_both_formats_whatever_the_output_format(self):
		self.assertEqual(to_db_date("19-08-2026"), "2026-08-19")
		self.assertEqual(to_db_date("19-08-2026 14:03:05"), "2026-08-19 14:03:05")
		self.assertEqual(to_db_date("2026-08-19"), "2026-08-19")

	def test_non_dates_are_untouched(self):
		for value in ("ACC-SINV-2026-00001", "", 5, None, "1-2-3"):
			self.assertEqual(to_db_date(value), value)


if __name__ == "__main__":
	unittest.main()
