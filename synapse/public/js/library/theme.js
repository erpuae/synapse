// Copyright (c) 2026, Dxbitz and contributors
// Shared helpers for the Synapse component library. Every colour, number and
// date passes through here so the whole library reads one theme and formats the
// same way the Frappe desk does. No renderer hardcodes a colour or a format.

// Read a CSS custom property, resolved against a specific element so a nested
// [data-theme="dark"] subtree gives dark values. Falls back to the document.
export function cssVar(name, el) {
	const node = el || document.documentElement;
	const value = getComputedStyle(node).getPropertyValue(name);
	return (value || "").trim();
}

// Frappe palette families we map short colour tokens onto. A token like "blue"
// becomes the theme's --blue-500, which changes with light and dark on its own.
const PALETTE_FAMILIES = new Set([
	"blue", "green", "red", "orange", "yellow", "purple",
	"pink", "cyan", "teal", "violet", "gray", "grey",
]);

// Resolve one colour the author gave into a concrete value. A hex passes
// through, a "--var" is read from the theme, and a palette token like "blue" or
// "green-600" becomes the matching theme variable. Anything else is returned as
// is and left for the browser to judge.
export function resolveColor(token, el) {
	if (typeof token !== "string" || !token) return token;
	const t = token.trim();

	if (t.startsWith("#") || t.startsWith("rgb") || t.startsWith("hsl")) return t;
	if (t.startsWith("--")) return cssVar(t, el) || t;

	const family = t.includes("-") ? t.split("-")[0] : t;
	if (PALETTE_FAMILIES.has(family)) {
		const name = t.includes("-") ? `--${t}` : `--${t}-500`;
		return cssVar(name, el) || t;
	}
	return t;
}

// The colours option, resolved. Returns undefined when the author gave none, so
// the chart inherits the frappe-charts default palette and looks exactly like a
// desk chart with no colours set. Only when the author names colours do we
// resolve them from the theme.
export function resolveColors(colors, el) {
	if (!Array.isArray(colors) || !colors.length) return undefined;
	return colors.map((c) => resolveColor(c, el));
}

// Format one value for a typed table or list cell, using the desk's own
// formatters so a Synapse table reads the same as a report. Unknown types fall
// back to a plain string.
export function formatValue(value, type, options) {
	const opts = options || {};
	if (value === null || value === undefined || value === "") return "";

	try {
		switch (type) {
			case "currency":
				if (window.format_currency) return format_currency(value, opts.currency);
				return String(value);
			case "int":
				if (window.frappe && frappe.format_number) return frappe.format_number(value, null, 0);
				return String(Math.round(value));
			case "float":
			case "number":
				if (window.frappe && frappe.format_number) return frappe.format_number(value, null, opts.precision);
				return String(value);
			case "percent":
				if (window.frappe && frappe.format_number) return frappe.format_number(value, null, opts.precision) + "%";
				return value + "%";
			case "date":
				if (window.frappe && frappe.datetime && frappe.datetime.str_to_user) {
					return frappe.datetime.str_to_user(value);
				}
				return String(value);
			case "link":
			case "text":
			default:
				return String(value);
		}
	} catch (e) {
		return String(value);
	}
}

// Empty a container before a re-render, dropping any chart instance so no orphan
// SVG is left behind. Charts store their instance on the element; we forget it.
export function clearEl(el) {
	if (!el) return;
	if (el.__synapseChart) {
		try {
			el.__synapseChart = null;
		} catch (e) {
			/* nothing to do */
		}
	}
	el.innerHTML = "";
}

// A labelled placeholder, used when a component key is unknown, a component is
// not implemented, or data does not fit its template. Never throws.
export function placeholder(el, message, sub) {
	clearEl(el);
	const box = document.createElement("div");
	box.className = "synapse-placeholder";
	const title = document.createElement("div");
	title.className = "synapse-placeholder-title";
	title.textContent = message || "Nothing to show";
	box.appendChild(title);
	if (sub) {
		const s = document.createElement("div");
		s.className = "synapse-placeholder-sub";
		s.textContent = sub;
		box.appendChild(s);
	}
	el.appendChild(box);
	return box;
}

// A titled shell every widget sits in, so titles and spacing match across the
// library. Returns the body element to fill.
export function shell(el, title) {
	clearEl(el);
	const wrap = document.createElement("div");
	wrap.className = "synapse-component";
	if (title) {
		const h = document.createElement("div");
		h.className = "synapse-component-title";
		h.textContent = title;
		wrap.appendChild(h);
	}
	const body = document.createElement("div");
	body.className = "synapse-component-body";
	wrap.appendChild(body);
	el.appendChild(wrap);
	return body;
}

// True when frappe-charts is on the page. Every chart renderer checks this and
// degrades to a placeholder rather than throwing when it is missing.
export function chartsAvailable() {
	return !!(window.frappe && frappe.Chart);
}
