# Copyright (c) 2026, Dxbitz and contributors
"""MCP Settings — the site's allowlist for the MCP endpoint.

Read by synapse.mcp_tools.settings, which turns this document into the pure
Policy that synapse.mcp_tools.policy checks. Nothing here grants a
permission: a tick is a ceiling, and the user still needs the matching Frappe
permission on the DocType.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from synapse.mcp_tools.settings import HARD_ROW_CAP


class MCPSettings(Document):
	def validate(self):
		self._dedupe_doctypes()
		self._dedupe_denied()
		self._dedupe_roles()
		self._clamp_row_limit()
		self._warn_if_writes_unreachable()

	def on_update(self):
		# A Single is cached in redis and again on frappe.local for the request,
		# so an edit is invisible to the endpoint until both are dropped.
		from synapse.mcp_tools import settings

		frappe.clear_cache(doctype=self.doctype)
		settings.clear_cache()

	def _dedupe_doctypes(self):
		seen = set()
		for row in self.allowed_doctypes or []:
			if row.document_type in seen:
				frappe.throw(_("{0} is listed twice in Allowed DocTypes.").format(row.document_type))
			seen.add(row.document_type)

	def _dedupe_denied(self):
		seen = set()
		for row in self.denied_doctypes or []:
			if row.document_type in seen:
				frappe.throw(_("{0} is listed twice in Blocked DocTypes.").format(row.document_type))
			seen.add(row.document_type)

	def _dedupe_roles(self):
		seen = set()
		for row in self.role_permissions or []:
			if row.role in seen:
				frappe.throw(_("{0} is listed twice in Role Permissions.").format(row.role))
			seen.add(row.role)

	def _clamp_row_limit(self):
		if not self.max_rows or self.max_rows < 1:
			self.max_rows = 100
		elif self.max_rows > HARD_ROW_CAP:
			self.max_rows = HARD_ROW_CAP

	def _warn_if_writes_unreachable(self):
		"""Say so rather than leaving someone to debug a refusal.

		Write tools switched on with no role granted a write action is a valid
		state — it is how you stage the configuration — but it is almost always
		a half-finished edit.
		"""

		if not self.enable_write_tools:
			return

		granted = any(
			row.allow_write or row.allow_submit or row.allow_cancel or row.allow_delete
			for row in self.role_permissions or []
		)
		if not granted:
			frappe.msgprint(
				_("Write tools are enabled but no role is granted a write action, so every write will be refused."),
				indicator="orange",
				alert=True,
			)
