# Copyright (c) 2026, Dxbitz and contributors
"""JSON-RPC dispatch and the tool registry for the vendored MCP core.

See synapse/mcp_core/__init__.py for why this is vendored rather than
installed. Adapted from frappe/frappe-mcp (MIT).

The one behavioural addition over upstream is per-tool authorization. A tool
declares the roles allowed to call it:

	@mcp.tool(roles=["MCP Agent"])
	def get_doc(...): ...

A user who does not hold one of them never sees the tool in `tools/list` and is
refused by `tools/call`. Hiding it matters as much as refusing it — a listed
tool the model cannot call becomes a retry loop.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from synapse.mcp_core.schema import (
	InvalidArguments,
	build_input_schema,
	split_docstring,
	validate_arguments,
)

__all__ = ["MCP", "Tool", "ToolAnnotations"]

JSONRPC_VERSION = "2.0"

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602

# Newest first. The client's requested version is echoed when we speak it,
# otherwise it gets our newest and decides whether to continue.
SUPPORTED_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")


@dataclass
class ToolAnnotations:
	"""Client-facing hints. `readOnlyHint` is the one that matters here — some
	clients auto-approve a read-only tool and prompt for anything else."""

	title: str | None = None
	readOnlyHint: bool | None = None
	destructiveHint: bool | None = None
	idempotentHint: bool | None = None
	openWorldHint: bool | None = None

	def as_dict(self) -> dict:
		return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass
class Tool:
	name: str
	description: str
	input_schema: dict
	fn: Callable
	roles: tuple[str, ...] = ()
	annotations: ToolAnnotations | None = None
	enabled: Callable[[], bool] | None = field(default=None)

	def as_listing(self) -> dict:
		listing = {
			"name": self.name,
			"description": self.description,
			"inputSchema": self.input_schema,
		}
		if self.annotations:
			listing["annotations"] = self.annotations.as_dict()
		return listing


class MCP:
	"""One MCP server. Create a single instance per app and register tools on it."""

	def __init__(self, name: str, version: str = "1.0.0", on_refusal: Callable | None = None):
		"""
		Args:
			name: Server name reported to clients at `initialize`.
			version: Server version reported at `initialize`.
			on_refusal: Called as (tool_name, reason, tool_or_None) when a call
				is turned away before the tool body runs — unknown tool, missing
				role, bad arguments. The app uses it to keep those attempts in
				its audit trail; without it they would leave no trace, which is
				the opposite of what an audit trail is for.
		"""

		self._name = name
		self._version = version
		self._on_refusal = on_refusal
		self._tools: dict[str, Tool] = {}
		self._entry_fn: Callable | None = None

	# ── registration ──────────────────────────────────────────────────────────
	def register(self, *, allow_guest: bool = False):
		"""Wrap a function as the whitelisted Frappe endpoint for this server.

		The decorated function runs before each request, which is where tool
		modules get imported. Keep its body to imports — it runs on every
		JSON-RPC call including `ping`.
		"""

		import frappe
		from werkzeug.wrappers import Response

		whitelister = frappe.whitelist(allow_guest=allow_guest, methods=["GET", "POST"])

		def decorator(fn):
			if self._entry_fn is not None:
				raise Exception("mcp.register can be used only once per MCP instance")

			self._entry_fn = fn

			def wrapper() -> Response:
				fn()
				return self.handle(frappe.request, Response())

			return whitelister(wrapper)

		return decorator

	def tool(
		self,
		*,
		name: str | None = None,
		description: str | None = None,
		roles: list[str] | tuple[str, ...] | None = None,
		annotations: ToolAnnotations | None = None,
		enabled: Callable[[], bool] | None = None,
	):
		"""Register a function as a tool.

		The description and the per-argument descriptions come from a
		Google-style docstring; the input schema comes from the signature.

		Args:
			name: Tool name. Defaults to the function name.
			description: Overrides the docstring summary.
			roles: Roles allowed to call it. Any one is enough. Empty means any
				authenticated user, which for this app is almost never right.
			annotations: Client hints — set readOnlyHint on read tools.
			enabled: Optional predicate evaluated per request. Returning False
				hides the tool, which is how site settings switch groups of
				tools off without unregistering them.
		"""

		def decorator(fn: Callable):
			summary, arg_docs = split_docstring(fn.__doc__)
			schema = build_input_schema(fn)

			for arg_name, spec in schema["properties"].items():
				if arg_name in arg_docs:
					spec["description"] = arg_docs[arg_name]

			tool = Tool(
				name=name or fn.__name__,
				description=description or summary,
				input_schema=schema,
				fn=fn,
				roles=tuple(roles or ()),
				annotations=annotations,
				enabled=enabled,
			)
			self._tools[tool.name] = tool
			return fn

		return decorator

	# ── request handling ──────────────────────────────────────────────────────
	def handle(self, request, response):
		if request.method != "POST":
			response.status_code = 405
			return response

		try:
			data = request.get_json(force=True)
		except Exception:
			return _error(response, None, PARSE_ERROR, "Parse error")

		if not isinstance(data, dict):
			# Batches were removed from MCP in 2025-06-18 and are not accepted.
			return _error(response, None, INVALID_REQUEST, "Invalid Request")

		method = data.get("method") or ""

		if isinstance(method, str) and method.startswith("notifications/"):
			response.status_code = 202
			return response

		request_id = data.get("id")
		if request_id is None:
			return _error(response, None, INVALID_REQUEST, "Invalid Request")

		params = data.get("params") or {}
		if not isinstance(params, dict):
			return _error(response, request_id, INVALID_PARAMS, "Invalid params")

		match method:
			case "initialize":
				result = self._initialize(params)
			case "ping":
				result = {}
			case "tools/list":
				result = {"tools": [t.as_listing() for t in self._visible_tools()]}
			case "tools/call":
				result = self._call_tool(params)
			case _:
				return _error(response, request_id, METHOD_NOT_FOUND, "Method not found")

		return _success(response, request_id, result)

	def _initialize(self, params: dict) -> dict:
		requested = params.get("protocolVersion")
		protocol = requested if requested in SUPPORTED_PROTOCOLS else SUPPORTED_PROTOCOLS[0]

		return {
			"protocolVersion": protocol,
			"serverInfo": {"name": self._name, "version": self._version},
			"capabilities": {"tools": {"listChanged": False}},
		}

	def _call_tool(self, params: dict) -> dict:
		name = params.get("name")
		arguments = params.get("arguments") or {}

		tool = self._tools.get(name)
		if tool is None or not _is_enabled(tool):
			return self._refuse(name, f"Tool '{name}' is not available.", tool)

		if not _has_any_role(tool.roles):
			needed = " or ".join(tool.roles)
			return self._refuse(
				name, f"Not permitted. The '{needed}' role is required to call '{name}'.", tool
			)

		try:
			validated = validate_arguments(arguments, tool.input_schema)
		except InvalidArguments as e:
			return self._refuse(name, str(e), tool)

		try:
			return _tool_result(tool.fn(**validated))
		except Exception as e:
			# The tools log and shape their own failures; this is the backstop
			# for anything that escapes. One line, no traceback to the client.
			_log_exception(name)
			return _tool_error(f"{type(e).__name__}: {str(e).strip().splitlines()[0][:400]}")

	def _refuse(self, name, reason: str, tool: Tool | None) -> dict:
		"""Record the attempt, then hand the reason back to the caller."""

		if self._on_refusal:
			try:
				self._on_refusal(name, reason, tool)
			except Exception:
				_log_exception("refusal hook")

		return _tool_error(reason)

	def _visible_tools(self) -> list[Tool]:
		return [t for t in self._tools.values() if _is_enabled(t) and _has_any_role(t.roles)]


# ── helpers ───────────────────────────────────────────────────────────────────
def _is_enabled(tool: Tool) -> bool:
	if tool.enabled is None:
		return True

	try:
		return bool(tool.enabled())
	except Exception:
		_log_exception(f"{tool.name} (enabled check)")
		return False


def _has_any_role(roles: tuple[str, ...]) -> bool:
	if not roles:
		return True

	import frappe

	user = getattr(frappe.session, "user", None)
	if not user or user == "Guest":
		return False

	held = set(frappe.get_roles(user))
	return any(role in held for role in roles)


def _log_exception(label: str):
	try:
		import frappe

		frappe.log_error(title=f"MCP tool failed: {label}"[:140], message=frappe.get_traceback())
	except Exception:
		pass


def _tool_result(value: Any) -> dict:
	text = value if isinstance(value, str) else _dumps(value)
	result: dict[str, Any] = {"content": [{"type": "text", "text": text}], "isError": False}

	if isinstance(value, dict):
		result["structuredContent"] = value

	return result


def _tool_error(message: str) -> dict:
	# An MCP tool failure is a successful JSON-RPC response carrying isError, so
	# the model can read the reason and correct itself instead of the client
	# treating it as a transport fault.
	return {"content": [{"type": "text", "text": message}], "isError": True}


def _dumps(value: Any) -> str:
	try:
		return json.dumps(value, default=str)
	except Exception:
		return str(value)


def _success(response, request_id, result):
	payload = {"jsonrpc": JSONRPC_VERSION, "id": request_id, "result": result or {}}
	response.data = _dumps(payload)
	response.mimetype = "application/json"
	response.status_code = 200
	return response


def _error(response, request_id, code, message):
	payload = {
		"jsonrpc": JSONRPC_VERSION,
		"id": request_id,
		"error": {"code": code, "message": message},
	}
	response.data = _dumps(payload)
	response.mimetype = "application/json"
	response.status_code = 400
	return response
