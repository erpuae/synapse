// Copyright (c) 2026, Dxbitz and contributors
// Views one Synapse Page by name from the route /app/synapse-view/<name>. It
// fetches the page's layout and hands it to the M0/M1 library to lay onto the
// 12-column grid. It wires no data source; each block renders its frozen data.

frappe.pages["synapse-view"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Synapse View"),
		single_column: true,
	});
	wrapper.__synapse = new SynapsePageView(page);
};

frappe.pages["synapse-view"].on_page_show = function (wrapper) {
	if (wrapper.__synapse) wrapper.__synapse.load();
};

class SynapsePageView {
	constructor(page) {
		this.page = page;
		this.load();
	}

	route_name() {
		const route = frappe.get_route() || [];
		return route[1] || null;
	}

	load() {
		if (!(window.synapse && synapse.library && synapse.library.render_page)) {
			this.page.main.html(placeholder("Library bundle not loaded", "Run bench build --app synapse and reload."));
			return;
		}

		const name = this.route_name();
		if (!name) {
			this.page.main.html(placeholder("No page named", "Open /app/synapse-view/<name>, or pick a Synapse Page from the list."));
			return;
		}

		this.page.main.html(`<div class="text-muted" style="padding:24px;">${__("Loading...")}</div>`);
		frappe.call("synapse.api.get_page_layout", { name }).then(
			(r) => {
				const model = r && r.message;
				if (!model) {
					this.page.main.html(placeholder("Page not found", name));
					return;
				}
				this.page.set_title(model.title || name);
				const host = document.createElement("div");
				this.page.main.empty().append(host);
				synapse.library.render_page(host, model);
			},
			() => this.page.main.html(placeholder("Could not load page", name)),
		);
	}
}

function placeholder(title, sub) {
	return (
		`<div class="synapse-placeholder" style="margin:24px;">` +
		`<div class="synapse-placeholder-title">${frappe.utils.escape_html(title)}</div>` +
		(sub ? `<div class="synapse-placeholder-sub">${frappe.utils.escape_html(sub)}</div>` : "") +
		`</div>`
	);
}
