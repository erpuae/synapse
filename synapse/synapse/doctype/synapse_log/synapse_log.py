# Copyright (c) 2026, Dxbitz and contributors
"""Audit trail for the Synapse endpoint — one row per call, read or write.

Rows are written by synapse.mcp_tools.audit with db_insert and their own
commit, so a rejected or rolled back call still leaves its record. Nothing here
is meant to be created or edited from the desk; the DocType grants read and
report to System Manager only.
"""

import frappe
from frappe.model.document import Document


class SynapseLog(Document):
	pass


def delete_old_logs():
	"""Daily. Drop rows past the retention window set in Synapse Settings."""

	from synapse.mcp_tools.settings import retention_days

	cutoff = frappe.utils.add_days(frappe.utils.nowdate(), -retention_days())
	frappe.db.delete("Synapse Log", {"creation": ("<", cutoff)})
	frappe.db.commit()
