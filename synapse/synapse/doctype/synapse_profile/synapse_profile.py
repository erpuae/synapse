# Copyright (c) 2026, Dxbitz and contributors
"""Synapse Profile, a named bundle of access granted to a set of roles.

This is the primary grant. A user's reach through the Synapse endpoint is the
union of every enabled profile whose roles they hold: the DocType Access grid of
each, or unrestricted if Full Access is ticked. synapse.mcp_tools.settings reads
the profiles matching the calling user and folds them into the request's Policy.

Nothing here bypasses Frappe. A tick is a ceiling; the user still needs the
matching Frappe permission on the record, which is checked when the document is
actually touched. The site backstop in Synapse Settings, and the always-blocked
and always-read-only sets in policy.py, override anything a profile grants.
"""

import frappe
from frappe import _
from frappe.model.document import Document


class SynapseProfile(Document):
	def validate(self):
		self._dedupe_roles()
		self._dedupe_doctypes()
		self._dedupe_tools()
		self._warn_if_writes_unreachable()
		self._warn_if_custom_tools_off()

	def on_update(self):
		# The Policy is built per request from the profiles matching the caller,
		# and cached on frappe.local. Drop it so an edit takes effect at once.
		from synapse.mcp_tools import settings

		settings.clear_cache()

	def on_trash(self):
		from synapse.mcp_tools import settings

		settings.clear_cache()

	def _dedupe_roles(self):
		seen = set()
		for row in self.roles or []:
			if row.role in seen:
				frappe.throw(_("{0} is listed twice in Roles.").format(row.role))
			seen.add(row.role)

	def _dedupe_doctypes(self):
		if self.full_access:
			return

		seen = set()
		for row in self.doctype_access or []:
			if row.document_type in seen:
				frappe.throw(_("{0} is listed twice in DocType Access.").format(row.document_type))
			seen.add(row.document_type)

	def _dedupe_tools(self):
		seen = set()
		for row in self.custom_tools or []:
			name = (row.tool or "").strip()
			if name in seen:
				frappe.throw(_("{0} is listed twice in Allowed Custom Tools.").format(name))
			seen.add(name)

	def _warn_if_custom_tools_off(self):
		"""Say so when a profile lists custom tools but the site switch is off."""

		if not self.enabled or not (self.custom_tools or []):
			return

		if not frappe.db.get_single_value("Synapse Settings", "enable_custom_tools"):
			frappe.msgprint(
				_("This profile lists custom tools, but 'Enable Custom Tools' is off in Synapse Settings, so none of them will run."),
				indicator="orange",
				alert=True,
			)

	def _warn_if_writes_unreachable(self):
		"""Flag the common half-finished edit rather than leaving a silent refusal.

		A profile granting a write action is inert until 'Enable Write Tools' is
		ticked in Synapse Settings. That is a valid staging state, but it is
		almost always an oversight, so say so.
		"""

		if not self.enabled:
			return

		grants_write = bool(self.full_access) or any(
			row.allow_write or row.allow_submit or row.allow_cancel or row.allow_delete or row.allow_operate
			for row in self.doctype_access or []
		)
		if not grants_write:
			return

		if not frappe.db.get_single_value("Synapse Settings", "enable_write_tools"):
			frappe.msgprint(
				_("This profile grants a write action, but 'Enable Write Tools' is off in Synapse Settings, so those actions will be refused."),
				indicator="orange",
				alert=True,
			)
