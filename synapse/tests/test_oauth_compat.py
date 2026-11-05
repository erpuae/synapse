"""Tests for the Frappe v15 OAuth discovery layer (synapse.oauth_compat).

Covers the parts that decide safety and version behaviour without a request:
which redirect URIs a self-registering client may use, and when the layer
stands aside for Frappe v16's own OAuth Settings.
"""

import unittest
from unittest import mock

import frappe

from synapse import compat
from synapse.oauth_compat import MAX_REDIRECT_URIS, validate_redirect_uris


class TestRedirectUris(unittest.TestCase):
	def ok(self, uris):
		cleaned, problem = validate_redirect_uris(uris)
		self.assertIsNone(problem, problem)
		return cleaned

	def bad(self, uris):
		_, problem = validate_redirect_uris(uris)
		self.assertIsNotNone(problem, f"{uris!r} should be refused")

	def test_accepts_https_and_loopback_http(self):
		self.ok(["https://claude.ai/api/mcp/auth_callback"])
		self.ok(["http://localhost:33418/callback"])
		self.ok(["http://127.0.0.1:6274/oauth/callback"])
		self.ok(["http://[::1]:8080/cb"])

	def test_deduplicates_and_keeps_order(self):
		self.assertEqual(
			self.ok(["https://a.example/cb", "https://b.example/cb", "https://a.example/cb"]),
			["https://a.example/cb", "https://b.example/cb"],
		)

	def test_refuses_unsafe_schemes(self):
		self.bad(["javascript:alert(1)"])
		self.bad(["data:text/html,hi"])
		self.bad(["ftp://a.example/cb"])
		self.bad(["http://evil.example/cb"])
		self.bad(["http://localhost.evil.example/cb"])

	def test_refuses_malformed(self):
		self.bad([])
		self.bad(None)
		self.bad("https://a.example/cb")
		self.bad([""])
		self.bad([123])
		self.bad(["https://a.example/cb#frag"])
		self.bad(["https://a.example/c b"])
		self.bad(["https:///no-host"])
		self.bad(["https://a.example/" + "x" * 200])
		self.bad([f"https://a.example/{i}" for i in range(MAX_REDIRECT_URIS + 1)])


class TestVersionSwitch(unittest.TestCase):
	def test_v15_uses_synapse_layer(self):
		with mock.patch.object(frappe, "__version__", "15.126.0"):
			self.assertEqual(compat.frappe_major_version(), 15)
			self.assertFalse(compat.native_oauth_discovery())

	def test_v16_uses_frappe(self):
		for version in ("16.0.0", "16.3.1-dev", "17.0.0"):
			with mock.patch.object(frappe, "__version__", version):
				self.assertTrue(compat.native_oauth_discovery(), version)

	def test_unparseable_version_falls_back_to_layer(self):
		with mock.patch.object(frappe, "__version__", "develop"):
			self.assertEqual(compat.frappe_major_version(), 0)
			self.assertFalse(compat.native_oauth_discovery())
