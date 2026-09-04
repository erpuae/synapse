// Copyright (c) 2026, Dxbitz and contributors
// The one registry that maps a component_type to its renderer. The page grid
// (M1) and the catalog tool (M4) both read this, so there is a single source of
// truth. An unknown key resolves to a labelled placeholder, never a crash.

import * as charts from "./charts.js";
import * as widgets from "./widgets.js";
import * as layout from "./layout.js";
import { placeholder } from "./theme.js";

// component_type -> render(el, config, data)
export const RENDERERS = {
	// Group A: charts (adapters over frappe-charts)
	bar_chart: charts.bar_chart,
	bar_horizontal: charts.bar_horizontal, // not native in this build, placeholder
	line_chart: charts.line_chart,
	area_chart: charts.area_chart,
	scatter_chart: charts.scatter_chart, // not native in this build, placeholder
	pie_chart: charts.pie_chart,
	donut_chart: charts.donut_chart,
	percentage_chart: charts.percentage_chart,
	mixed_chart: charts.mixed_chart,
	heatmap: charts.heatmap,
	map: charts.map, // deferred, placeholder

	// Group B: widgets
	number_card: widgets.number_card,
	table: widgets.table,
	list: widgets.list,
	progress: widgets.progress,
	pivot: widgets.pivot,
	callout: widgets.callout,
	text_block: widgets.text_block,

	// Group C: layout primitives
	section_break: layout.section_break,
	column_break: layout.column_break,
	spacer: layout.spacer,
};

// Look up a renderer. Never returns undefined: an unknown key gives a renderer
// that draws a labelled placeholder naming the missing type.
export function resolve(componentType) {
	const fn = RENDERERS[componentType];
	if (fn) return fn;
	return function unknown(el) {
		return placeholder(el, "Unknown component", `No renderer for "${componentType}"`);
	};
}

// The one entry point callers use. Renders componentType into el from
// (config, data), catching anything a renderer throws so one bad component can
// never take down the page.
export function render(el, componentType, config, data) {
	const fn = resolve(componentType);
	try {
		return fn(el, config || {}, data || {});
	} catch (e) {
		return placeholder(el, "This component could not render", String(e && e.message ? e.message : e));
	}
}

export function known_types() {
	return Object.keys(RENDERERS);
}
