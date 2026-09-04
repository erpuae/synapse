# Copyright (c) 2026, Dxbitz and contributors
"""Synapse Component: the catalog record for one visual component.

Each record carries the component's key (the component_type the JS registry
resolves), its label and group, its data_template and options_schema as JSON
Schema, a description written for an LLM to read, and the is_layout and
not_implemented flags. The records are seeded from synapse.components.catalog,
which is the single source of truth; editing them by hand is not the intended
path, so a migrate re-seeds them.
"""

from frappe.model.document import Document


class SynapseComponent(Document):
	pass
