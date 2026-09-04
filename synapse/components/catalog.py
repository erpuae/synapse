# Copyright (c) 2026, Dxbitz and contributors
"""The component catalog: the single source of truth for every visual component.

Each entry pins three things the rest of the system reads:

* data_template, the JSON Schema the baked frozen_data must match. The
  author-time validator (M2) and the LLM (M4) both use it.
* options_schema, the JSON Schema for the config keys the component accepts.
  Anything outside it is ignored, never passed through to the renderer.
* description, written for an LLM to choose the component.

The JS registry (synapse/public/js/library/registry.js) holds the matching
renderers, keyed by the same `key`. seed() writes these into Synapse Component
records; it is idempotent, so a migrate keeps the records in step with this file.

Three keys are seeded as not_implemented, because this bench's frappe-charts
(2.0.0-rc27) does not draw them and faking a look is not allowed:
scatter_chart, bar_horizontal and map.
"""

import json

import frappe

# ── shared schema fragments ───────────────────────────────────────────────────

_AXIS_DATA = {
	"type": "object",
	"required": ["labels", "series"],
	"additionalProperties": False,
	"properties": {
		"labels": {"type": "array", "items": {"type": ["string", "number"]}},
		"series": {
			"type": "array",
			"minItems": 1,
			"items": {
				"type": "object",
				"required": ["name", "values"],
				"additionalProperties": False,
				"properties": {
					"name": {"type": "string"},
					"values": {"type": "array", "items": {"type": ["number", "null"]}},
					"chartType": {"type": "string", "enum": ["bar", "line"]},
				},
			},
		},
		"axes": {
			"type": "object",
			"additionalProperties": False,
			"properties": {"x": {"type": "string"}, "y": {"type": "string"}},
		},
	},
}

_PART_DATA = {
	"type": "object",
	"required": ["labels", "values"],
	"additionalProperties": False,
	"properties": {
		"labels": {"type": "array", "items": {"type": "string"}},
		"values": {"type": "array", "items": {"type": "number"}},
	},
}

_HEATMAP_DATA = {
	"type": "object",
	"required": ["dataPoints"],
	"additionalProperties": False,
	"properties": {
		"dataPoints": {"type": "object", "additionalProperties": {"type": "number"}},
		"start": {"type": "string"},
		"end": {"type": "string"},
	},
}

_EMPTY_DATA = {"type": "object", "additionalProperties": False}

_AXIS_OPTIONS = {
	"type": "object",
	"additionalProperties": False,
	"properties": {
		"title": {"type": "string"},
		"colors": {"type": "array", "items": {"type": "string"}},
		"height": {"type": "number"},
		"animate": {"type": "boolean"},
		"stacked": {"type": "boolean"},
		"bar_space_ratio": {"type": "number"},
		"region_fill": {"type": "boolean"},
		"hide_dots": {"type": "boolean"},
		"heatline": {"type": "boolean"},
		"value_labels": {"type": "boolean"},
		"x_axis_mode": {"type": "string", "enum": ["span", "tick"]},
		"y_axis_mode": {"type": "string", "enum": ["span", "tick"]},
		"shorten_y_numbers": {"type": "boolean"},
		"x_is_series": {"type": "boolean"},
		"truncate_legends": {"type": "boolean"},
	},
}

_PART_OPTIONS = {
	"type": "object",
	"additionalProperties": False,
	"properties": {
		"title": {"type": "string"},
		"colors": {"type": "array", "items": {"type": "string"}},
		"height": {"type": "number"},
		"animate": {"type": "boolean"},
		"max_slices": {"type": "number"},
		"max_legend_points": {"type": "number"},
		"truncate_legends": {"type": "boolean"},
	},
}

_HEATMAP_OPTIONS = {
	"type": "object",
	"additionalProperties": False,
	"properties": {
		"title": {"type": "string"},
		"height": {"type": "number"},
		"colors": {"type": "array", "items": {"type": "string"}},
		"discrete_domains": {"type": "boolean"},
		"count_label": {"type": "string"},
	},
}

_VALUE_TYPES = ["currency", "int", "float", "number", "percent"]


# ── the catalog ───────────────────────────────────────────────────────────────

COMPONENTS = [
	# Group A: charts
	{
		"key": "bar_chart",
		"label": "Bar Chart",
		"group": "Chart",
		"description": "Vertical bars over categories. Use to compare a measure across a small set of labels, or to show one or more series side by side.",
		"data_template": _AXIS_DATA,
		"options_schema": _AXIS_OPTIONS,
	},
	{
		"key": "line_chart",
		"label": "Line Chart",
		"group": "Chart",
		"description": "A line over an ordered axis. Use for a trend over time or another ordered dimension.",
		"data_template": _AXIS_DATA,
		"options_schema": _AXIS_OPTIONS,
	},
	{
		"key": "area_chart",
		"label": "Area Chart",
		"group": "Chart",
		"description": "A line with the region under it filled. Use for a trend where the magnitude matters as much as the shape.",
		"data_template": _AXIS_DATA,
		"options_schema": _AXIS_OPTIONS,
	},
	{
		"key": "mixed_chart",
		"label": "Mixed Chart",
		"group": "Chart",
		"description": "Bars and lines on one axis. Set each series' chartType to bar or line. Use to show a total as bars with a rate or average as a line.",
		"data_template": _AXIS_DATA,
		"options_schema": _AXIS_OPTIONS,
	},
	{
		"key": "pie_chart",
		"label": "Pie Chart",
		"group": "Chart",
		"description": "Parts of a whole as slices. Use for a small number of shares that add up to a total.",
		"data_template": _PART_DATA,
		"options_schema": _PART_OPTIONS,
	},
	{
		"key": "donut_chart",
		"label": "Donut Chart",
		"group": "Chart",
		"description": "Parts of a whole as a ring. Same use as a pie, with a hole in the middle.",
		"data_template": _PART_DATA,
		"options_schema": _PART_OPTIONS,
	},
	{
		"key": "percentage_chart",
		"label": "Percentage Chart",
		"group": "Chart",
		"description": "A single horizontal bar split into shares. Use for a compact parts-of-a-whole where a pie would be too heavy.",
		"data_template": _PART_DATA,
		"options_schema": _PART_OPTIONS,
	},
	{
		"key": "heatmap",
		"label": "Heatmap",
		"group": "Chart",
		"description": "A GitHub-style calendar of daily counts. dataPoints maps unix-second day keys to a number. Use for activity over a year.",
		"data_template": _HEATMAP_DATA,
		"options_schema": _HEATMAP_OPTIONS,
	},
	# Not native in this frappe-charts build. Flagged stubs.
	{
		"key": "scatter_chart",
		"label": "Scatter Chart",
		"group": "Chart",
		"not_implemented": True,
		"note": "frappe-charts 2.0.0-rc27 in this bench does not draw scatter. Deferred pending a decision (upgrade frappe-charts or accept a custom renderer).",
		"description": "Points on an x and y axis (the dots element). Not available in this bench's frappe-charts.",
		"data_template": _AXIS_DATA,
		"options_schema": _AXIS_OPTIONS,
	},
	{
		"key": "bar_horizontal",
		"label": "Horizontal Bar Chart",
		"group": "Chart",
		"not_implemented": True,
		"note": "frappe-charts in this bench has no horizontal-bar option. For a top-N horizontal bar, use the list widget, which draws a proportional bar per row.",
		"description": "Horizontal bars over categories. Not available in this bench's frappe-charts.",
		"data_template": _AXIS_DATA,
		"options_schema": _AXIS_OPTIONS,
	},
	{
		"key": "map",
		"label": "Map",
		"group": "Chart",
		"not_implemented": True,
		"note": "A geographic map needs a separate mapping library (Leaflet or similar). Out of Phase 1 scope, decide the library before building.",
		"description": "A geographic map. Not part of frappe-charts and not built in Phase 1.",
		"data_template": _EMPTY_DATA,
		"options_schema": {"type": "object", "additionalProperties": False, "properties": {"title": {"type": "string"}}},
	},
	# Group B: widgets
	{
		"key": "number_card",
		"label": "Number Card",
		"group": "Widget",
		"description": "One headline metric, with an optional delta and up or down trend arrow. Use for a single KPI.",
		"data_template": {
			"type": "object",
			"required": ["value"],
			"additionalProperties": False,
			"properties": {
				"value": {"type": "number"},
				"label": {"type": "string"},
				"delta": {"type": "number"},
				"trend": {"type": "string", "enum": ["up", "down", "flat"]},
			},
		},
		"options_schema": {
			"type": "object",
			"additionalProperties": False,
			"properties": {
				"title": {"type": "string"},
				"value_type": {"type": "string", "enum": _VALUE_TYPES},
				"currency": {"type": "string"},
				"precision": {"type": "number"},
				"delta_type": {"type": "string", "enum": _VALUE_TYPES},
				"delta_is_percent": {"type": "boolean"},
			},
		},
	},
	{
		"key": "table",
		"label": "Table",
		"group": "Widget",
		"description": "Typed columns and rows. Each column has a type (text, link, currency, int, float, percent, date) that decides its formatting and alignment.",
		"data_template": {
			"type": "object",
			"required": ["columns", "rows"],
			"additionalProperties": False,
			"properties": {
				"columns": {
					"type": "array",
					"items": {
						"type": "object",
						"required": ["key", "label"],
						"additionalProperties": False,
						"properties": {
							"key": {"type": "string"},
							"label": {"type": "string"},
							"type": {"type": "string", "enum": ["text", "link", "currency", "int", "float", "number", "percent", "date"]},
							"precision": {"type": "number"},
						},
					},
				},
				"rows": {"type": "array", "items": {"type": "object"}},
			},
		},
		"options_schema": {
			"type": "object",
			"additionalProperties": False,
			"properties": {"title": {"type": "string"}, "currency": {"type": "string"}},
		},
	},
	{
		"key": "list",
		"label": "List",
		"group": "Widget",
		"description": "Compact labelled rows, top-N style: a label, a value, and an optional proportional bar behind the row (bar is 0 to 1).",
		"data_template": {
			"type": "object",
			"required": ["items"],
			"additionalProperties": False,
			"properties": {
				"items": {
					"type": "array",
					"items": {
						"type": "object",
						"required": ["label", "value"],
						"additionalProperties": False,
						"properties": {
							"label": {"type": "string"},
							"value": {"type": "number"},
							"bar": {"type": "number", "minimum": 0, "maximum": 1},
						},
					},
				}
			},
		},
		"options_schema": {
			"type": "object",
			"additionalProperties": False,
			"properties": {
				"title": {"type": "string"},
				"value_type": {"type": "string", "enum": _VALUE_TYPES},
				"currency": {"type": "string"},
				"precision": {"type": "number"},
			},
		},
	},
	{
		"key": "progress",
		"label": "Progress",
		"group": "Widget",
		"description": "A value against a target as a bar, with the figures and a percentage. Use for collected versus goal, or done versus planned.",
		"data_template": {
			"type": "object",
			"required": ["value", "target"],
			"additionalProperties": False,
			"properties": {
				"value": {"type": "number"},
				"target": {"type": "number"},
				"label": {"type": "string"},
			},
		},
		"options_schema": {
			"type": "object",
			"additionalProperties": False,
			"properties": {
				"title": {"type": "string"},
				"value_type": {"type": "string", "enum": _VALUE_TYPES},
				"currency": {"type": "string"},
			},
		},
	},
	{
		"key": "pivot",
		"label": "Pivot",
		"group": "Widget",
		"description": "A rows by columns grid of one measure. rowLabels and colLabels are the headers, cells is a rows-by-columns matrix. Use for a measure cross-tabulated by two dimensions.",
		"data_template": {
			"type": "object",
			"required": ["rowLabels", "colLabels", "cells"],
			"additionalProperties": False,
			"properties": {
				"rowLabels": {"type": "array", "items": {"type": "string"}},
				"colLabels": {"type": "array", "items": {"type": "string"}},
				"cells": {"type": "array", "items": {"type": "array", "items": {"type": ["number", "null"]}}},
				"corner": {"type": "string"},
				"measureType": {"type": "string", "enum": _VALUE_TYPES},
			},
		},
		"options_schema": {
			"type": "object",
			"additionalProperties": False,
			"properties": {
				"title": {"type": "string"},
				"value_type": {"type": "string", "enum": _VALUE_TYPES},
				"currency": {"type": "string"},
				"row_totals": {"type": "boolean"},
			},
		},
	},
	{
		"key": "callout",
		"label": "Callout",
		"group": "Widget",
		"description": "A short, levelled note: info, success, warning or danger, with a title and body. Use to flag one thing that needs attention.",
		"data_template": {
			"type": "object",
			"required": ["level"],
			"additionalProperties": False,
			"properties": {
				"level": {"type": "string", "enum": ["info", "success", "warning", "danger"]},
				"title": {"type": "string"},
				"body": {"type": "string"},
			},
		},
		"options_schema": {"type": "object", "additionalProperties": False, "properties": {"title": {"type": "string"}}},
	},
	{
		"key": "text_block",
		"label": "Text Block",
		"group": "Widget",
		"description": "A block of markdown. Use for a heading, a note or a short narrative between other components.",
		"data_template": {
			"type": "object",
			"additionalProperties": False,
			"anyOf": [{"required": ["markdown"]}, {"required": ["text"]}],
			"properties": {"markdown": {"type": "string"}, "text": {"type": "string"}},
		},
		"options_schema": {"type": "object", "additionalProperties": False},
	},
	# Group C: layout primitives
	{
		"key": "section_break",
		"label": "Section Break",
		"group": "Layout",
		"is_layout": True,
		"description": "A divider that starts a new section, with an optional title. Carries no data.",
		"data_template": _EMPTY_DATA,
		"options_schema": {"type": "object", "additionalProperties": False, "properties": {"title": {"type": "string"}}},
	},
	{
		"key": "column_break",
		"label": "Column Break",
		"group": "Layout",
		"is_layout": True,
		"description": "A break that moves following components into the next column of the grid. Carries no data.",
		"data_template": _EMPTY_DATA,
		"options_schema": {"type": "object", "additionalProperties": False},
	},
	{
		"key": "spacer",
		"label": "Spacer",
		"group": "Layout",
		"is_layout": True,
		"description": "Vertical space of a given height in pixels. Carries no data.",
		"data_template": _EMPTY_DATA,
		"options_schema": {"type": "object", "additionalProperties": False, "properties": {"height": {"type": "number"}}},
	},
]


def catalog() -> list:
	"""The component definitions, as plain dicts."""

	return COMPONENTS


def seed():
	"""Upsert one Synapse Component record per catalog entry. Idempotent."""

	for c in COMPONENTS:
		values = {
			"label": c["label"],
			"component_group": c.get("group"),
			"is_layout": 1 if c.get("is_layout") else 0,
			"not_implemented": 1 if c.get("not_implemented") else 0,
			"description": c.get("description", ""),
			"note": c.get("note", ""),
			"data_template": json.dumps(c["data_template"], indent=2),
			"options_schema": json.dumps(c["options_schema"], indent=2),
		}

		if frappe.db.exists("Synapse Component", c["key"]):
			doc = frappe.get_doc("Synapse Component", c["key"])
			doc.update(values)
			doc.save(ignore_permissions=True)
		else:
			doc = frappe.get_doc({"doctype": "Synapse Component", "key": c["key"], **values})
			doc.insert(ignore_permissions=True)

	frappe.db.commit()
	print(f"Seeded {len(COMPONENTS)} Synapse Component records on {frappe.local.site}.")
