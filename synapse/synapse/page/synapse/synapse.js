// Copyright (c) 2026, Dxbitz and contributors
// The Synapse admin console. System Manager only (enforced by the Page roles).
// A copiable endpoint link on top, and a sidebar of the actions an admin needs:
// profiles, settings, logs and a readiness check.

frappe.pages["synapse"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Synapse"),
		single_column: false,
	});

	new SynapseConsole(page);
};

class SynapseConsole {
	constructor(page) {
		this.page = page;
		this.build_sidebar();
		this.render_loading();
		frappe.call("synapse.api.connect_context").then((r) => {
			this.ctx = (r && r.message) || {};
			this.render();
		});
	}

	build_sidebar() {
		const actions = [
			{ label: __("New Profile"), icon: "add", onclick: () => frappe.new_doc("Synapse Profile") },
			{ label: __("Profiles"), icon: "assign", onclick: () => frappe.set_route("List", "Synapse Profile") },
			{ label: __("Settings"), icon: "setting-gear", onclick: () => frappe.set_route("Form", "Synapse Settings", "Synapse Settings") },
			{ label: __("Audit Log"), icon: "list-alt", onclick: () => frappe.set_route("List", "Synapse Log") },
			{ label: __("Health Check"), icon: "refresh", onclick: () => this.health_check() },
		];

		const $s = $(`<div class="synapse-sidebar"></div>`).appendTo(this.page.sidebar);
		$(`<div class="text-muted" style="font-size:11px;text-transform:uppercase;letter-spacing:.5px;margin:6px 0 10px;">${__("Manage")}</div>`).appendTo($s);

		actions.forEach((a) => {
			const $item = $(
				`<a class="synapse-action" href="#" style="display:flex;align-items:center;gap:8px;padding:7px 8px;border-radius:6px;color:var(--text-color);text-decoration:none;">
					<span>${frappe.utils.icon(a.icon, "sm")}</span><span>${a.label}</span>
				</a>`
			).appendTo($s);
			$item.on("click", (e) => {
				e.preventDefault();
				a.onclick();
			});
			$item.on("mouseenter", () => $item.css("background", "var(--fg-hover-color, #f4f4f5)"));
			$item.on("mouseleave", () => $item.css("background", "transparent"));
		});
	}

	render_loading() {
		this.page.main.html(`<div class="text-muted" style="padding:40px;">${__("Loading…")}</div>`);
	}

	render() {
		const endpoint = frappe.utils.escape_html(this.ctx.endpoint || "");
		this.page.main.html(`
			<div style="max-width:760px;">
				<div class="synapse-card" style="border:1px solid var(--border-color);border-radius:10px;padding:20px 22px;margin-bottom:18px;background:var(--card-bg,var(--fg-color));">
					<div style="font-weight:600;margin-bottom:4px;">${__("MCP Endpoint")}</div>
					<div class="text-muted" style="font-size:12px;margin-bottom:12px;">${__("Give this URL to an MCP client. Callers authenticate over OAuth as their own Frappe user.")}</div>
					<div style="display:flex;gap:8px;align-items:center;">
						<input type="text" readonly class="form-control" style="font-family:monospace;font-size:13px;" value="${endpoint}">
						<button class="btn btn-primary btn-sm synapse-copy" style="white-space:nowrap;">${__("Copy")}</button>
					</div>
				</div>
				<div class="synapse-card" style="border:1px solid var(--border-color);border-radius:10px;padding:20px 22px;">
					<div style="font-weight:600;margin-bottom:8px;">${__("How access works")}</div>
					<div class="text-muted" style="font-size:13px;line-height:1.6;">
						${__("Nothing is reachable until a Synapse Profile grants it. A user's access is the union of every enabled profile whose roles they hold, and their own Frappe permissions always apply on top. Every call is written to the Audit Log.")}
					</div>
					<div style="margin-top:14px;">
						<button class="btn btn-default btn-sm synapse-go-profiles">${__("Set up a profile")}</button>
						<button class="btn btn-default btn-sm synapse-go-health" style="margin-left:6px;">${__("Run health check")}</button>
					</div>
				</div>
			</div>
		`);

		this.page.main.find(".synapse-copy").on("click", () => this.copy(this.ctx.endpoint));
		this.page.main.find(".synapse-go-profiles").on("click", () => frappe.set_route("List", "Synapse Profile"));
		this.page.main.find(".synapse-go-health").on("click", () => this.health_check());
	}

	copy(text) {
		if (!text) return;
		frappe.utils.copy_to_clipboard(text);
	}

	health_check() {
		frappe.call("synapse.api.readiness_report").then((r) => {
			const text = (r && r.message) || __("No output.");
			const d = new frappe.ui.Dialog({ title: __("Synapse Health Check"), size: "large" });
			$(`<pre style="white-space:pre-wrap;font-size:12px;line-height:1.5;margin:0;">${frappe.utils.escape_html(text)}</pre>`).appendTo(d.body);
			d.show();
		});
	}
}
