// Copyright (c) 2026, Dxbitz and contributors
// The user-facing Synapse shortcut. It rides on the User form, so a user reaches
// it from their own profile ("My Settings"). It appears only on your own profile
// and only if one of your roles is carried by a Synapse Profile, otherwise there
// is nothing to connect to and the button stays hidden. All it offers is the MCP
// link to copy and a short note on what it is.

frappe.ui.form.on("User", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.name !== frappe.session.user) {
			return;
		}

		frappe.call("synapse.api.connect_context").then((r) => {
			const ctx = (r && r.message) || {};
			if (!ctx.covered) {
				return;
			}

			frm.add_custom_button(__("Connect to Synapse"), () => show_synapse_connect(ctx.endpoint));
		});
	},
});

function show_synapse_connect(endpoint) {
	const url = endpoint || "";
	const d = new frappe.ui.Dialog({ title: __("Connect to Synapse") });

	$(`
		<div style="font-size:13px;line-height:1.6;">
			<p class="text-muted" style="margin-bottom:12px;">
				${__("Synapse lets an AI assistant read and write this ERP as you, under your own permissions. Add the link below to an MCP client (for example Claude), then sign in with your usual login when it asks.")}
			</p>
			<div style="font-weight:600;margin-bottom:6px;">${__("Your MCP link")}</div>
			<div style="display:flex;gap:8px;align-items:center;">
				<input type="text" readonly class="form-control" style="font-family:monospace;font-size:12px;" value="${frappe.utils.escape_html(url)}">
				<button class="btn btn-primary btn-sm synapse-copy" style="white-space:nowrap;">${__("Copy")}</button>
			</div>
			<p class="text-muted" style="font-size:12px;margin-top:12px;">
				${__("The assistant only ever sees what your roles allow. Every action it takes is logged.")}
			</p>
		</div>
	`).appendTo(d.body);

	d.$wrapper.find(".synapse-copy").on("click", () => {
		if (url) frappe.utils.copy_to_clipboard(url);
	});
	d.show();
}
