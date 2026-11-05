# Copyright (c) 2026, Dxbitz and contributors
"""Frappe version differences Synapse has to know about.

Kept import-light on purpose: hooks.py imports it, and hooks are loaded in
every process, before a site or database is necessarily there.
"""

import frappe


def frappe_major_version() -> int:
	try:
		return int(str(frappe.__version__).split(".")[0])
	except (ValueError, AttributeError):
		return 0


def native_oauth_discovery() -> bool:
	"""True when Frappe itself serves the MCP OAuth discovery documents and
	dynamic client registration (Frappe v16+, switched on in OAuth Settings).

	False on v15, where synapse.oauth_compat serves them instead.
	"""

	return frappe_major_version() >= 16
