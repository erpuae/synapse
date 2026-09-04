# Copyright (c) 2026, Dxbitz and contributors
"""Synapse Page: an ordered list of blocks laid out on a 12-column grid.

Each block names a component (a catalog key), a column span, and the config and
frozen data it renders from. The renderer (synapse/public/js/library/grid.js)
reads this and places the blocks. In M1 the data is baked into each block; no
data source is wired.

This controller does only the cheap, structural checks: the span is in range and
the JSON parses. Full validation of each block against its component's
data_template and options_schema is M2.
"""

import json

import frappe
from frappe import _
from frappe.model.document import Document

FULL_WIDTH_ONLY = {"section_break", "spacer"}


class SynapsePage(Document):
	def validate(self):
		for i, block in enumerate(self.blocks or [], start=1):
			self._clamp_columns(block)
			self._check_json(block, "config", i)
			self._check_json(block, "frozen_data", i)

	def _clamp_columns(self, block):
		if block.component_type in FULL_WIDTH_ONLY:
			block.columns = 12
			return
		try:
			cols = int(block.columns or 12)
		except (TypeError, ValueError):
			cols = 12
		block.columns = max(1, min(cols, 12))

	def _check_json(self, block, field, row):
		raw = block.get(field)
		if not raw:
			return
		try:
			json.loads(raw)
		except Exception as e:
			frappe.throw(_("Block {0}: {1} is not valid JSON ({2}).").format(row, field, str(e)))
