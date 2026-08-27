# Copyright (c) 2026, Dxbitz and contributors
"""Synapse Settings — the site-wide switches and the backstop denylist.

Access is not granted here. It is granted by Synapse Profile records, whose
roles decide who gets what; this page only holds the master switches, the row
and date limits, and the backstop list of DocTypes no agent may touch whatever
a profile allows. synapse.mcp_tools.settings reads all of it into the pure
Policy that synapse.mcp_tools.policy checks.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from synapse.mcp_tools.settings import HARD_ROW_CAP


class SynapseSettings(Document):
	def validate(self):
		self._dedupe_denied()
		self._clamp_row_limit()

	def on_update(self):
		# A Single is cached in redis and again on frappe.local for the request,
		# so an edit is invisible to the endpoint until both are dropped.
		from synapse.mcp_tools import settings

		frappe.clear_cache(doctype=self.doctype)
		settings.clear_cache()

	def _dedupe_denied(self):
		seen = set()
		for row in self.denied_doctypes or []:
			if row.document_type in seen:
				frappe.throw(_("{0} is listed twice in Blocked DocTypes.").format(row.document_type))
			seen.add(row.document_type)

	def _clamp_row_limit(self):
		if not self.max_rows or self.max_rows < 1:
			self.max_rows = 100
		elif self.max_rows > HARD_ROW_CAP:
			self.max_rows = HARD_ROW_CAP
