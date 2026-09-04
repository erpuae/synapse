"""Registration test for custom tools.

Pure stdlib, extend.py's decorator imports nothing from frappe, so this runs
under plain pytest as well as `bench run-tests --app synapse`. Only the loader
touches frappe, and the loader is not exercised here.
"""

import unittest

from synapse.extend import _REGISTRY, ExternalTool, tool


class TestToolDecorator(unittest.TestCase):
	def setUp(self):
		_REGISTRY.clear()

	def tearDown(self):
		_REGISTRY.clear()

	def test_bare_decorator_uses_function_name(self):
		@tool
		def alpha(x: int) -> dict:
			return {"x": x}

		self.assertIn("alpha", _REGISTRY)
		self.assertIsInstance(_REGISTRY["alpha"], ExternalTool)
		self.assertFalse(_REGISTRY["alpha"].read_only)

	def test_called_decorator_sets_metadata(self):
		@tool(name="beta_tool", read_only=True, destructive=False, description="does beta")
		def beta():
			return {}

		ext = _REGISTRY["beta_tool"]
		self.assertEqual(ext.name, "beta_tool")
		self.assertTrue(ext.read_only)
		self.assertEqual(ext.description, "does beta")

	def test_decorator_returns_the_original_function(self):
		def gamma(a, b):
			return {"sum": a + b}

		wrapped = tool(gamma)
		self.assertIs(wrapped, gamma)
		self.assertEqual(gamma(1, 2), {"sum": 3})

	def test_two_tools_coexist(self):
		@tool
		def one():
			return {}

		@tool
		def two():
			return {}

		self.assertEqual({"one", "two"}, set(_REGISTRY))


if __name__ == "__main__":
	unittest.main()
