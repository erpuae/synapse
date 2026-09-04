# Copyright (c) 2026, Dxbitz and contributors
"""Custom tools contributed by other apps.

Any installed app can add its own tools to the Synapse endpoint. An app writes a
plain function, marks it with the `@synapse.tool` decorator, and lists the module
in its hooks:

	# in myapp/hooks.py
	synapse_tools = ["myapp.synapse_tools"]

	# in myapp/synapse_tools.py
	import synapse

	@synapse.tool(read_only=True)
	def open_tasks_for(project: str) -> dict:
		"A short description the model sees. Args come from the signature."
		...

The function runs the same way the built-in tools do. It runs as the signed in
user, with Frappe permissions on, and every call is written to the Synapse Log.
The tool author is responsible for whatever the function does, so it should read
and write through the normal Frappe document API and never with permissions off.

A custom tool is not reachable just because it is registered. Two things must
also be true: the site has *Enable Custom Tools* ticked in Synapse Settings, and
a Synapse Profile the caller holds lists the tool by name. This is the same
explicit grant model the rest of Synapse uses. Full Access does not include
custom tools, because a custom tool can run any code its author wrote.

This module keeps no import of frappe or of the MCP server at load time. The
decorator only records the function. The wiring into the server happens in
load_external_tools(), which the endpoint calls on each request.
"""

import functools
from collections.abc import Callable
from dataclasses import dataclass

__all__ = ["tool", "registered_tools", "load_external_tools"]


@dataclass
class ExternalTool:
	fn: Callable
	name: str
	app: str | None = None
	description: str | None = None
	read_only: bool = False
	destructive: bool = False


# name -> ExternalTool. Filled by the decorator when an app's tool module is
# imported, read by load_external_tools() to wire each one into the server.
_REGISTRY: dict[str, ExternalTool] = {}


def tool(
	_fn: Callable | None = None,
	*,
	name: str | None = None,
	description: str | None = None,
	read_only: bool = False,
	destructive: bool = False,
):
	"""Mark a function as a Synapse custom tool.

	Args:
		name: Tool name shown to the client. Defaults to the function name. Give
			it an app prefix (for example "pms_open_tasks") so two apps cannot
			clash. A name that clashes with a built-in tool is refused at load.
		description: Overrides the function's docstring summary.
		read_only: Sets the client's read-only hint. Set it to True only for a
			tool that never writes.
		destructive: Sets the client's destructive hint for a tool that changes
			or removes data.
	"""

	def register(fn: Callable) -> Callable:
		tname = name or fn.__name__
		_REGISTRY[tname] = ExternalTool(
			fn=fn,
			name=tname,
			app=getattr(fn, "__module__", "").split(".", 1)[0] or None,
			description=description,
			read_only=read_only,
			destructive=destructive,
		)
		return fn

	# Allow both @tool and @tool(...).
	if callable(_fn):
		return register(_fn)
	return register


def registered_tools() -> dict[str, ExternalTool]:
	"""The custom tools imported so far. Import the hook modules first if empty."""

	if not _REGISTRY:
		_import_tool_modules()
	return dict(_REGISTRY)


def load_external_tools() -> None:
	"""Import every app's tool modules and wire each new tool into the server.

	Called from the endpoint on each request. It is cheap to repeat: module
	imports are cached by Python, and a tool already on the server is skipped, so
	nothing is registered twice. A custom tool whose name clashes with a built-in
	is skipped and logged, never allowed to shadow it.
	"""

	from synapse.mcp import mcp
	from synapse.mcp_core import ToolAnnotations
	from synapse.mcp_tools import audit, settings

	_import_tool_modules()

	for ext in list(_REGISTRY.values()):
		if ext.name in mcp._tools:
			# Either already wired, or a clash with a built-in tool. If the tool
			# on the server is not this one, refuse to overwrite it.
			existing = mcp._tools[ext.name]
			if getattr(existing, "_synapse_external", False):
				continue
			_log(f"Custom tool '{ext.name}' clashes with a built-in and was skipped.")
			continue

		_wire(mcp, ToolAnnotations, audit, settings, ext)


def _import_tool_modules() -> None:
	import importlib

	import frappe

	for path in frappe.get_hooks("synapse_tools") or []:
		try:
			importlib.import_module(path)
		except Exception:
			_log(f"Could not import synapse_tools module '{path}'.")


def _wire(mcp, ToolAnnotations, audit, settings, ext: ExternalTool) -> None:
	runner = _make_runner(audit, ext)
	audited = audit.audited(audit.CUSTOM, tool=ext.name)(runner)
	audited._synapse_external = True

	annotations = ToolAnnotations(
		title=ext.name,
		readOnlyHint=ext.read_only,
		destructiveHint=ext.destructive or None,
	)

	def enabled(_name=ext.name):
		return settings.custom_tool_enabled(_name)

	registered = mcp.tool(
		name=ext.name,
		description=ext.description,
		annotations=annotations,
		enabled=enabled,
	)(audited)

	# Mark the Tool object so a repeat load knows this name is ours, not a clash.
	tool_obj = mcp._tools.get(ext.name)
	if tool_obj is not None:
		tool_obj._synapse_external = True

	return registered


def _make_runner(audit, ext: ExternalTool):
	"""Wrap the author's function so its arguments are audited and its return is a dict."""

	@functools.wraps(ext.fn)
	def runner(**kwargs):
		entry = audit.current()
		if entry is not None:
			entry.sent(kwargs)

		result = ext.fn(**kwargs)
		if not isinstance(result, dict):
			return {"result": result}
		return result

	return runner


def _log(message: str) -> None:
	try:
		import frappe

		frappe.log_error(title="Synapse custom tool", message=message)
	except Exception:
		pass
