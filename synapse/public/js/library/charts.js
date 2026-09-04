// Copyright (c) 2026, Dxbitz and contributors
// Group A: chart elements. Every renderer here is a thin adapter over
// frappe-charts (the same library the Frappe desk draws with), fed our
// normalised shape. We never reimplement a chart the library already draws, so
// a Synapse chart and a desk chart of the same type look the same and any
// frappe-charts upgrade carries through.
//
// frappe-charts 2.0.0-rc27 (bundled with Frappe 16) draws: line, bar, pie,
// donut, percentage, heatmap and axis-mixed. It does NOT draw scatter, and it
// has no horizontal-bar option. Those two, like map, render as a labelled
// not-implemented placeholder rather than a faked look.

import { chartsAvailable, clearEl, placeholder, resolveColors } from "./theme.js";

const DEFAULT_HEIGHT = 240;

// ── shared builders ───────────────────────────────────────────────────────────

// Mount a frappe-charts config on the element, replacing any previous chart so
// no orphan SVG is left behind.
function mount(el, cfg) {
	clearEl(el);
	try {
		el.__synapseChart = new frappe.Chart(el, cfg);
	} catch (e) {
		placeholder(el, "This chart could not be drawn", String(e && e.message ? e.message : e));
	}
	return el.__synapseChart;
}

// Options every axis and part-to-whole chart shares. Only keys in the
// options_schema are read; anything else on config is ignored, never passed
// blindly into frappe-charts.
function commonOptions(config, el) {
	const cfg = {};
	const colors = resolveColors(config.colors, el);
	if (colors) cfg.colors = colors;
	cfg.height = Number(config.height) || DEFAULT_HEIGHT;
	if (config.animate === false) cfg.animate = 0;
	if (config.truncate_legends) cfg.truncateLegends = 1;
	return cfg;
}

function validAxisData(data) {
	return (
		data &&
		Array.isArray(data.labels) &&
		Array.isArray(data.series) &&
		data.series.length > 0 &&
		data.series.every((s) => s && Array.isArray(s.values))
	);
}

// Build an axis chart (bar, line, area, mixed) from {labels, series, axes}.
function axisChart(el, config, data, type, perDatasetType) {
	if (!chartsAvailable()) return placeholder(el, "Charts are not loaded on this page");
	if (!validAxisData(data)) {
		return placeholder(el, "Chart data does not fit its template", "Expected { labels: [...], series: [{ name, values }] }");
	}

	const datasets = data.series.map((s) => {
		const ds = { name: s.name, values: s.values };
		if (perDatasetType && s.chartType) ds.chartType = s.chartType;
		return ds;
	});

	const cfg = {
		type,
		data: { labels: data.labels, datasets },
		...commonOptions(config, el),
	};

	// Axis passthroughs, all optional and all real frappe-charts keys.
	const axisOptions = {};
	if (config.x_axis_mode) axisOptions.xAxisMode = config.x_axis_mode; // "span" | "tick"
	if (config.y_axis_mode) axisOptions.yAxisMode = config.y_axis_mode;
	if (config.shorten_y_numbers) axisOptions.shortenYAxisNumbers = 1;
	if (config.x_is_series) axisOptions.xIsSeries = 1;
	if (Object.keys(axisOptions).length) cfg.axisOptions = axisOptions;

	if (config.stacked || config.bar_space_ratio !== undefined) {
		cfg.barOptions = {};
		if (config.stacked) cfg.barOptions.stacked = 1;
		if (config.bar_space_ratio !== undefined) cfg.barOptions.spaceRatio = Number(config.bar_space_ratio);
	}

	const lineOptions = {};
	if (config.region_fill) lineOptions.regionFill = 1; // area fill under the line
	if (config.hide_dots) lineOptions.hideDots = 1;
	if (config.heatline) lineOptions.heatline = 1;
	if (Object.keys(lineOptions).length) cfg.lineOptions = lineOptions;

	if (config.value_labels) cfg.valuesOverPoints = 1;

	if (data.axes && (data.axes.x || data.axes.y)) {
		cfg.axisOptions = cfg.axisOptions || {};
		// frappe-charts has no axis title; we keep the labels on the config for
		// the tooltip formatter and any future use, without inventing UI.
	}

	return mount(el, cfg);
}

function validPartData(data) {
	return data && Array.isArray(data.labels) && Array.isArray(data.values) && data.values.length > 0;
}

// Build a part-to-whole chart (pie, donut, percentage) from {labels, values}.
function partChart(el, config, data, type) {
	if (!chartsAvailable()) return placeholder(el, "Charts are not loaded on this page");
	if (!validPartData(data)) {
		return placeholder(el, "Chart data does not fit its template", "Expected { labels: [...], values: [...] }");
	}

	const cfg = {
		type,
		data: { labels: data.labels, datasets: [{ values: data.values }] },
		...commonOptions(config, el),
	};
	if (config.max_slices) cfg.maxSlices = Number(config.max_slices);
	if (config.max_legend_points) cfg.maxLegendPoints = Number(config.max_legend_points);
	return mount(el, cfg);
}

// ── Group A renderers ─────────────────────────────────────────────────────────

export function bar_chart(el, config, data) {
	return axisChart(el, config, data, "bar", false);
}

export function line_chart(el, config, data) {
	return axisChart(el, config, data, "line", false);
}

export function area_chart(el, config, data) {
	// An area chart is a line with the region under it filled.
	return axisChart(el, { ...config, region_fill: true }, data, "line", false);
}

export function mixed_chart(el, config, data) {
	// axis-mixed reads each series' own chartType ("bar" or "line").
	return axisChart(el, config, data, "axis-mixed", true);
}

export function pie_chart(el, config, data) {
	return partChart(el, config, data, "pie");
}

export function donut_chart(el, config, data) {
	return partChart(el, config, data, "donut");
}

export function percentage_chart(el, config, data) {
	return partChart(el, config, data, "percentage");
}

export function heatmap(el, config, data) {
	if (!chartsAvailable()) return placeholder(el, "Charts are not loaded on this page");
	if (!data || typeof data.dataPoints !== "object") {
		return placeholder(el, "Heatmap data does not fit its template", "Expected { dataPoints: { <unix-second>: n }, start, end }");
	}
	const cfg = {
		type: "heatmap",
		data: {
			dataPoints: data.dataPoints,
			start: data.start ? new Date(data.start) : undefined,
			end: data.end ? new Date(data.end) : undefined,
		},
		height: Number(config.height) || DEFAULT_HEIGHT,
	};
	if (config.discrete_domains === false) cfg.discreteDomains = 0;
	if (config.count_label) cfg.countLabel = config.count_label;
	const colors = resolveColors(config.colors, el);
	if (colors) cfg.colors = colors;
	return mount(el, cfg);
}

// ── not native in this frappe-charts build ────────────────────────────────────
// Kept in the registry so the key resolves, but drawn as a flagged placeholder
// rather than a faked look. See the module header.

export function scatter_chart(el /* , config, data */) {
	return placeholder(
		el,
		"scatter_chart is not available",
		"frappe-charts 2.0.0-rc27 in this bench does not draw scatter. Deferred pending a decision.",
	);
}

export function bar_horizontal(el /* , config, data */) {
	return placeholder(
		el,
		"bar_horizontal is not available",
		"frappe-charts in this bench has no horizontal-bar option. Use the list widget for a top-N bar, or defer.",
	);
}

export function map(el /* , config, data */) {
	return placeholder(
		el,
		"map is not implemented",
		"A geographic map needs a separate mapping library (Leaflet or similar). Out of Phase 1 scope.",
	);
}
