app_name = "synapse"
app_title = "Synapse"
app_publisher = "Dxbitz"
app_description = "A permission-aware MCP server for Frappe and ERPNext"
app_email = "info@dxbitz.com"
app_license = "agpl-3.0"

# The MCP endpoint is served at:
#     POST /api/method/synapse.mcp.handle_mcp
# It is registered by the @mcp.register() decorator in synapse/mcp.py, which
# wraps frappe.whitelist, so there is no route to wire up here.

# Creates the MCP roles. Not a patch: Frappe records an app's patches as already
# applied when the app is first installed, so a patch would never run for a new
# installation.
after_install = "synapse.install.after_install"

scheduler_events = {
	"daily": [
		# Drop MCP Access Log rows past the retention window set in MCP Settings.
		"synapse.synapse.doctype.mcp_access_log.mcp_access_log.delete_old_logs",
	],
}
