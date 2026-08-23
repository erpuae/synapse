# Copyright (c) 2026, Dxbitz and contributors
"""Tool input schemas, docstring parsing and argument validation.

Pure stdlib — no frappe, no pydantic, no jsonschema — so it is unit testable
without a site and costs nothing to import. Adapted from frappe/frappe-mcp (MIT).

Three jobs:

1. `build_input_schema` turns a function signature into a JSON Schema object.
2. `split_docstring` pulls the summary and the per-argument descriptions out of
   a Google-style docstring so the model sees documented parameters.
3. `validate_arguments` checks an incoming `tools/call` payload against the
   schema. Deliberately shallow — types, required keys and unknown keys. Deep
   validation belongs in the tool, which has to be defensive anyway.
"""

import inspect
import re
import types
from collections.abc import Callable
from typing import Any, Union, get_args, get_origin, get_type_hints

__all__ = ["InvalidArguments", "build_input_schema", "split_docstring", "validate_arguments"]


_PY_TO_JSON = {
	int: "integer",
	str: "string",
	float: "number",
	bool: "boolean",
	type(None): "null",
}

# JSON has one number type; a schema saying "integer" must still accept 3.0.
# bool is a subclass of int in Python and must never satisfy "integer".
_JSON_TO_PY = {
	"string": str,
	"integer": int,
	"number": (int, float),
	"boolean": bool,
	"array": list,
	"object": dict,
	"null": type(None),
}


class InvalidArguments(Exception):
	"""Raised when tools/call arguments do not fit the tool's input schema."""


# ── schema generation ─────────────────────────────────────────────────────────
def build_input_schema(fn: Callable) -> dict:
	"""Return a JSON Schema object describing `fn`'s keyword parameters.

	*args and **kwargs are skipped: a tool that wants free-form input should
	declare a `dict` parameter so the shape stays visible to the model.
	"""

	try:
		hints = get_type_hints(fn)
	except (NameError, TypeError):
		hints = {}

	schema: dict[str, Any] = {"type": "object", "properties": {}}
	required: list[str] = []

	for name, param in inspect.signature(fn).parameters.items():
		if param.kind not in (
			inspect.Parameter.POSITIONAL_OR_KEYWORD,
			inspect.Parameter.KEYWORD_ONLY,
		):
			continue

		schema["properties"][name] = _to_json_schema(hints.get(name, Any))

		if param.default is inspect.Parameter.empty:
			required.append(name)

	if required:
		schema["required"] = required

	return schema


def _to_json_schema(py_type: Any) -> dict:
	if py_type is Any:
		return {}

	if py_type is list:
		return {"type": "array"}

	if py_type is dict:
		return {"type": "object"}

	if py_type in _PY_TO_JSON:
		return {"type": _PY_TO_JSON[py_type]}

	origin = get_origin(py_type)

	if origin in (Union, types.UnionType):
		return _union_schema(py_type)

	if origin is list:
		args = get_args(py_type)
		return {"type": "array", "items": _to_json_schema(args[0])} if args else {"type": "array"}

	if origin is dict:
		args = get_args(py_type)
		if len(args) == 2:
			return {"type": "object", "additionalProperties": _to_json_schema(args[1])}
		return {"type": "object"}

	# Anything else — a DocType class, a TypedDict, a forward ref that would not
	# resolve — is described as "no constraint" rather than guessed at.
	return {}


def _union_schema(py_type: Any) -> dict:
	args = get_args(py_type)
	has_none = any(arg is type(None) for arg in args)
	real = [arg for arg in args if arg is not type(None)]

	# Optional[T] collapses to {"type": [t, "null"]} where T is a simple type,
	# which reads better to a model than a one-branch anyOf.
	if has_none and len(real) == 1:
		inner = _to_json_schema(real[0])
		if "type" in inner and isinstance(inner["type"], str):
			inner["type"] = [inner["type"], "null"]
			return inner

	return {"anyOf": [_to_json_schema(arg) for arg in args]}


# ── docstrings ────────────────────────────────────────────────────────────────
_ARG_RE = re.compile(
	r"^\s*(\w+)\s*(?:\([^)]*\))?:\s*(.*?)(?=\n\s*\w+\s*(?:\(.*\))?:|\Z)",
	re.MULTILINE | re.DOTALL,
)


def split_docstring(doc: str | None) -> tuple[str, dict[str, str]]:
	"""Return (description, {arg_name: description}) from a Google-style docstring."""

	if not doc:
		return "", {}

	doc = inspect.cleandoc(doc)

	try:
		description, args_block = re.split(r"\n\s*Args:\n", doc, maxsplit=1)
	except ValueError:
		if doc.lstrip().startswith("Args:"):
			description, args_block = "", doc.lstrip()[len("Args:") :].lstrip()
		else:
			return doc, {}

	args = {
		name: " ".join(text.strip().split()) for name, text in _ARG_RE.findall(args_block)
	}
	return description.strip(), args


# ── argument validation ───────────────────────────────────────────────────────
def validate_arguments(arguments: dict, schema: dict) -> dict:
	"""Return the arguments the tool accepts, or raise InvalidArguments.

	Unknown keys are an error rather than being dropped silently: a model that
	invents a `filters` argument should be told, not handed a full-table read
	because its filter went in the bin.
	"""

	if not isinstance(arguments, dict):
		raise InvalidArguments("Arguments must be an object.")

	properties = schema.get("properties") or {}

	if unknown := sorted(set(arguments) - set(properties)):
		known = ", ".join(sorted(properties)) or "none"
		raise InvalidArguments(f"Unknown argument(s): {', '.join(unknown)}. Accepted: {known}.")

	if missing := sorted(set(schema.get("required") or []) - set(arguments)):
		raise InvalidArguments(f"Missing required argument(s): {', '.join(missing)}.")

	coerced = dict(arguments)
	for key, value in arguments.items():
		coerced[key] = _check_type(key, value, properties[key])

	return coerced


def _check_type(key: str, value: Any, spec: dict):
	"""Validate one argument against its schema type; return it, coerced if needed."""

	expected = spec.get("type")

	if expected is None:
		# {} (Any) or an anyOf branch we do not narrow. Let the tool decide.
		return value

	names = expected if isinstance(expected, list) else [expected]
	allowed = tuple(t for name in names for t in _as_tuple(_JSON_TO_PY.get(name)))

	if not allowed:
		return value

	# bool passes isinstance(x, int); JSON numbers are not booleans.
	if isinstance(value, bool) and "boolean" not in names:
		raise InvalidArguments(f"Argument '{key}' must be {' or '.join(names)}, got boolean.")

	# JSON has one number type, so a whole-number float (5.0) is a valid integer.
	# The schema layer's own contract says integer means the number type; accept
	# and coerce it rather than rejecting what a compliant client legitimately sends.
	if "integer" in names and isinstance(value, float) and value.is_integer():
		return int(value)

	if not isinstance(value, allowed):
		raise InvalidArguments(
			f"Argument '{key}' must be {' or '.join(names)}, got {type(value).__name__}."
		)

	return value


def _as_tuple(value) -> tuple:
	if value is None:
		return ()
	return value if isinstance(value, tuple) else (value,)
