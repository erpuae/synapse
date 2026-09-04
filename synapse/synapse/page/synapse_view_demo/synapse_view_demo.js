// Copyright (c) 2026, Dxbitz and contributors
// M1 demo harness. A hardcoded page model laid onto the 12-column grid, so the
// grid and the primitives can be eyeballed with no Synapse Page record and no
// data source. Resize the window to see the responsive collapse.

frappe.pages["synapse-view-demo"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Synapse Page Demo"),
		single_column: true,
	});

	if (!(window.synapse && synapse.library && synapse.library.render_page)) {
		page.main.html(
			`<div class="synapse-placeholder" style="margin:24px;"><div class="synapse-placeholder-title">Library bundle not loaded</div>` +
			`<div class="synapse-placeholder-sub">Run bench build --app synapse and reload.</div></div>`,
		);
		return;
	}

	const host = document.createElement("div");
	host.style.padding = "8px 4px";
	page.main.empty().append(host);
	synapse.library.render_page(host, demoPageModel());
};

function demoPageModel() {
	const months = ["Apr", "May", "Jun", "Jul", "Aug", "Sep"];
	const invoiced = [410000, 520000, 480000, 610000, 590000, 640000];
	const collected = [380000, 470000, 500000, 540000, 560000, 600000];

	return {
		title: "Receivables",
		blocks: [
			{ component_type: "section_break", columns: 12, config: { title: "Overview" }, frozen_data: {} },
			{ component_type: "number_card", columns: 4, config: { value_type: "currency", currency: "AED" },
				frozen_data: { value: 1840000, label: "Total outstanding", delta: -4.2, trend: "down" } },
			{ component_type: "number_card", columns: 4, config: { value_type: "currency", currency: "AED" },
				frozen_data: { value: 600000, label: "Collected this month", delta: 7.1, trend: "up" } },
			{ component_type: "number_card", columns: 4, config: { value_type: "int" },
				frozen_data: { value: 38, label: "Open invoices", delta: -3, trend: "down", delta_is_percent: false } },

			{ component_type: "section_break", columns: 12, config: { title: "Detail" }, frozen_data: {} },
			{ component_type: "bar_chart", columns: 8, config: { title: "Ageing (AED)" },
				frozen_data: { labels: ["0-30", "31-60", "61-90", ">90"], series: [{ name: "AED", values: [320000, 510000, 400000, 412000] }] } },
			{ component_type: "list", columns: 4, config: { title: "Top receivables", value_type: "currency", currency: "AED" },
				frozen_data: { items: [
					{ label: "Al Riqa Trading", value: 318000, bar: 1.0 },
					{ label: "Damac Interiors", value: 227500, bar: 0.72 },
					{ label: "Nakheel FitOut", value: 154000, bar: 0.48 } ] } },

			{ component_type: "line_chart", columns: 6, config: { title: "Collected (AED)" },
				frozen_data: { labels: months, series: [{ name: "Collected", values: collected }] } },
			{ component_type: "donut_chart", columns: 6, config: { title: "Invoice status" },
				frozen_data: { labels: ["Paid", "Overdue", "Draft"], values: [72, 21, 7] } },

			{ component_type: "table", columns: 12, config: { title: "Top customers", currency: "AED" },
				frozen_data: { columns: [
					{ key: "party", label: "Customer", type: "text" },
					{ key: "amt", label: "AED", type: "currency" },
					{ key: "due", label: "Due", type: "date" } ],
					rows: [
						{ party: "Al Riqa Trading", amt: 318000, due: "2026-09-20" },
						{ party: "Damac Interiors", amt: 227500, due: "2026-09-14" },
						{ party: "Nakheel FitOut", amt: 154000, due: "2026-10-02" } ] } },

			{ component_type: "callout", columns: 12, config: {},
				frozen_data: { level: "warning", title: "Overdue rising", body: "The 90+ bucket grew 8% week on week." } },
			{ component_type: "spacer", columns: 12, config: { height: 8 }, frozen_data: {} },
			{ component_type: "text_block", columns: 12, config: {},
				frozen_data: { markdown: "Collections are on track. Chase the 90+ bucket before month end." } },
		],
	};
}
