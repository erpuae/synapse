// Copyright (c) 2026, Dxbitz and contributors
// M0 demo harness. Renders every component from a hardcoded blob, in light and
// dark side by side, with no data source and no page builder. This is only for
// eyeballing the library; it wires nothing.

frappe.pages["synapse-components"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Synapse Components"),
		single_column: true,
	});
	new SynapseComponentGallery(page);
};

// One entry per component: the type, a config, and a hardcoded data blob that
// fits the component's data_template. UAE / AED flavoured, to match the house
// context. Layout and not-implemented components are included so the whole set
// can be seen at once.
function demoEntries() {
	const months = ["Apr", "May", "Jun", "Jul", "Aug", "Sep"];
	const invoiced = [410000, 520000, 480000, 610000, 590000, 640000];
	const collected = [380000, 470000, 500000, 540000, 560000, 600000];

	const heatPoints = {};
	const dayStart = Math.floor(Date.now() / 1000) - 120 * 86400;
	for (let i = 0; i < 120; i++) {
		if (i % 3 === 0) heatPoints[dayStart + i * 86400] = (i % 7) + 1;
	}

	return [
		{ heading: "Group A: charts (frappe-charts adapters)" },
		{ type: "bar_chart", config: { title: "Receivables ageing (AED)" },
			data: { labels: ["0-30", "31-60", "61-90", ">90"], series: [{ name: "AED", values: [320000, 510000, 400000, 412000] }] } },
		{ type: "line_chart", config: { title: "Monthly collected (AED)" },
			data: { labels: months, series: [{ name: "Collected", values: collected }] } },
		{ type: "area_chart", config: { title: "Monthly invoiced (AED)" },
			data: { labels: months, series: [{ name: "Invoiced", values: invoiced }] } },
		{ type: "mixed_chart", config: { title: "Invoiced vs collected" },
			data: { labels: months, series: [
				{ name: "Invoiced", values: invoiced, chartType: "bar" },
				{ name: "Collected", values: collected, chartType: "line" } ] } },
		{ type: "pie_chart", config: { title: "Invoice status" },
			data: { labels: ["Paid", "Overdue", "Draft"], values: [72, 21, 7] } },
		{ type: "donut_chart", config: { title: "Invoice status" },
			data: { labels: ["Paid", "Overdue", "Draft"], values: [72, 21, 7] } },
		{ type: "percentage_chart", config: { title: "Invoice status" },
			data: { labels: ["Paid", "Overdue", "Draft"], values: [72, 21, 7] } },
		{ type: "heatmap", config: { title: "Activity" },
			data: { dataPoints: heatPoints, start: new Date(dayStart * 1000).toISOString(), end: new Date().toISOString() } },
		{ type: "scatter_chart", config: { title: "Scatter (deferred)" }, data: {} },
		{ type: "bar_horizontal", config: { title: "Horizontal bar (deferred)" }, data: {} },
		{ type: "map", config: { title: "Map (deferred)" }, data: {} },

		{ heading: "Group B: widgets" },
		{ type: "number_card", config: { value_type: "currency", currency: "AED" },
			data: { value: 1840000, label: "Total outstanding", delta: -4.2, trend: "down" } },
		{ type: "table", config: { title: "Top customers", currency: "AED" },
			data: { columns: [
				{ key: "party", label: "Customer", type: "text" },
				{ key: "amt", label: "AED", type: "currency" },
				{ key: "due", label: "Due", type: "date" } ],
			rows: [
				{ party: "Al Riqa Trading", amt: 318000, due: "2026-09-20" },
				{ party: "Damac Interiors", amt: 227500, due: "2026-09-14" },
				{ party: "Nakheel FitOut", amt: 154000, due: "2026-10-02" } ] } },
		{ type: "list", config: { title: "Top receivables (AED)", value_type: "currency", currency: "AED" },
			data: { items: [
				{ label: "Al Riqa Trading", value: 318000, bar: 1.0 },
				{ label: "Damac Interiors", value: 227500, bar: 0.72 },
				{ label: "Nakheel FitOut", value: 154000, bar: 0.48 } ] } },
		{ type: "progress", config: { value_type: "currency", currency: "AED" },
			data: { value: 227000, target: 500000, label: "Collected MTD" } },
		{ type: "pivot", config: { title: "Ageing by customer", value_type: "currency", currency: "AED", row_totals: true },
			data: { corner: "Customer", rowLabels: ["Al Riqa", "Damac", "Nakheel"], colLabels: ["0-30", "31-60", ">60"],
				cells: [ [120000, 90000, 108000], [80000, 60000, 87500], [54000, 60000, 40000] ], measureType: "currency" } },
		{ type: "callout", config: {},
			data: { level: "warning", title: "Overdue rising", body: "90+ bucket up 8% week on week." } },
		{ type: "text_block", config: {},
			data: { markdown: "## Weekly summary\n\nCollections are **on track**. Watch the 90+ bucket, which grew this week." } },

		{ heading: "Group C: layout primitives" },
		{ type: "section_break", config: { title: "A section" }, data: {} },
		{ type: "column_break", config: {}, data: {} },
		{ type: "spacer", config: { height: 24 }, data: {} },
	];
}

class SynapseComponentGallery {
	constructor(page) {
		this.page = page;
		if (!(window.synapse && synapse.library && synapse.library.render)) {
			this.page.main.html(
				`<div class="synapse-placeholder" style="margin:20px;"><div class="synapse-placeholder-title">Library bundle not loaded</div>` +
				`<div class="synapse-placeholder-sub">Run <code>bench build --app synapse</code> and reload.</div></div>`,
			);
			return;
		}
		this.render();
	}

	render() {
		const entries = demoEntries();
		const root = $(`
			<div class="synapse-gallery-wrap" style="padding:16px;">
				<p class="text-muted" style="font-size:12px;margin-bottom:16px;">
					Every component from a hardcoded blob, light on the left and dark on the right. No data source is wired.
				</p>
				<div class="synapse-gallery-cols" style="display:grid;grid-template-columns:1fr 1fr;gap:20px;align-items:start;">
					<div class="synapse-gallery-light" data-band="light"></div>
					<div class="synapse-gallery-dark" data-theme="dark" data-band="dark"
						style="background:var(--bg-color);border-radius:10px;padding:12px;"></div>
				</div>
			</div>
		`);
		this.page.main.empty().append(root);

		["light", "dark"].forEach((band) => {
			const col = root.find(`[data-band="${band}"]`)[0];
			entries.forEach((entry) => this.renderEntry(col, entry, band));
		});
	}

	renderEntry(col, entry, band) {
		if (entry.heading) {
			const h = document.createElement("div");
			h.textContent = band === "light" ? entry.heading : " ";
			h.style.cssText = "font-weight:600;font-size:13px;margin:18px 0 8px;color:var(--text-color);";
			col.appendChild(h);
			return;
		}

		const card = document.createElement("div");
		card.style.cssText = "margin-bottom:14px;";
		const tag = document.createElement("div");
		tag.textContent = entry.type;
		tag.style.cssText = "font-size:10px;letter-spacing:.4px;text-transform:uppercase;color:var(--text-muted);margin-bottom:4px;font-family:var(--font-stack-mono,monospace);";
		card.appendChild(tag);

		const host = document.createElement("div");
		host.style.minWidth = "0";
		card.appendChild(host);
		col.appendChild(card);

		synapse.library.render(host, entry.type, entry.config, entry.data);
	}
}
