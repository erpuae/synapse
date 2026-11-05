# Copyright (c) 2026, Dxbitz and contributors
"""OAuth discovery for MCP clients on Frappe v15.

An MCP client (Claude, MCP Inspector, ...) finds out how to sign in by reading
three things the MCP authorization spec asks for:

	/.well-known/oauth-protected-resource     RFC 9728, named in our 401
	/.well-known/oauth-authorization-server   RFC 8414
	a registration endpoint                    RFC 7591, dynamic client registration

Frappe v16 serves all three itself, switched on in OAuth Settings. Frappe v15
has none of them. It only has /.well-known/openid-configuration, which leaves
out `jwks_uri`, so a client that falls back to it fails with
"expected string, received undefined" at path jwks_uri.

The OAuth server itself is fine on v15: authorize, consent, PKCE (S256), token,
refresh, revoke and Bearer validation all work. Only the discovery documents and
client registration are missing, so that is all this module adds. It points at
Frappe's own v15 endpoints and creates ordinary OAuth Client records.

On v16 this module stands aside. The routes are only wired in hooks.py on v15,
and every endpoint here answers 404 on v16, so it can never shadow or bypass
what OAuth Settings decides.
"""

import json
from urllib.parse import urlparse

import frappe
from werkzeug.wrappers import Response

from synapse.compat import native_oauth_discovery

MCP_PATH = "/api/method/synapse.mcp.handle_mcp"
OAUTH_BASE = "/api/method/frappe.integrations.oauth2"

# Scopes a registered client gets. Frappe's API access is the "all" scope;
# "openid" lets the client ask for an id_token too.
CLIENT_SCOPES = ("all", "openid")

# v15's token endpoint reads client_id from the form body. With HTTP Basic auth
# (client_secret_basic) it would look for a bearer token in the header instead
# and fail, so that method is never offered.
AUTH_METHODS = ("client_secret_post", "none")

MAX_REDIRECT_URIS = 10
MAX_REDIRECT_URI_LENGTH = 140  # OAuth Client.default_redirect_uri is a Data field
LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "::1")


# ── discovery documents ──────────────────────────────────────────────────────
@frappe.whitelist(allow_guest=True, methods=["GET"])
def authorization_server_metadata():
	"""RFC 8414 authorization server metadata, served at
	/.well-known/oauth-authorization-server on Frappe v15."""

	if native_oauth_discovery():
		return _json({"error": "not_found"}, 404)

	issuer = server_url()
	metadata = {
		"issuer": issuer,
		"authorization_endpoint": f"{issuer}{OAUTH_BASE}.authorize",
		"token_endpoint": f"{issuer}{OAUTH_BASE}.get_token",
		"revocation_endpoint": f"{issuer}{OAUTH_BASE}.revoke_token",
		"introspection_endpoint": f"{issuer}{OAUTH_BASE}.introspect_token",
		"userinfo_endpoint": f"{issuer}{OAUTH_BASE}.openid_profile",
		"response_types_supported": ["code"],
		"grant_types_supported": ["authorization_code", "refresh_token"],
		"code_challenge_methods_supported": ["S256"],
		"token_endpoint_auth_methods_supported": list(AUTH_METHODS),
		"scopes_supported": list(CLIENT_SCOPES),
	}
	if registration_enabled():
		metadata["registration_endpoint"] = f"{issuer}/api/method/synapse.oauth_compat.register_client"
	return _json(metadata)


@frappe.whitelist(allow_guest=True, methods=["GET"])
def protected_resource_metadata():
	"""RFC 9728 protected resource metadata, served at
	/.well-known/oauth-protected-resource on Frappe v15.

	The resource is the site origin rather than the endpoint path. An MCP client
	accepts metadata whose resource is a prefix of the URL it connected to, and
	the origin is a prefix of every path, including any later endpoint.
	"""

	if native_oauth_discovery():
		return _json({"error": "not_found"}, 404)

	base = server_url()
	return _json(
		{
			"resource": base,
			"authorization_servers": [base],
			"bearer_methods_supported": ["header"],
			"scopes_supported": ["all"],
			"resource_name": "Synapse",
		}
	)


# ── dynamic client registration ──────────────────────────────────────────────
def registration_enabled() -> bool:
	try:
		return bool(frappe.db.get_single_value("Synapse Settings", "allow_client_registration"))
	except Exception:
		return False


@frappe.whitelist(allow_guest=True, methods=["POST"])
def register_client():
	"""RFC 7591 dynamic client registration on Frappe v15.

	Creates an ordinary OAuth Client. Registering grants nothing by itself: a
	user still signs in to Frappe and approves the client on Frappe's own consent
	screen, and the token then carries that user's permissions only. The client
	is limited to System Users, the OAuth Client default.

	Off unless Synapse Settings > Allow Dynamic Client Registration is ticked,
	and rate limited per IP, since anyone can call it.
	"""

	if native_oauth_discovery():
		return _json({"error": "not_found"}, 404)
	if not registration_enabled():
		return _registration_error(
			"access_denied",
			"Dynamic client registration is off. Turn on Allow Dynamic Client Registration in Synapse Settings.",
			403,
		)

	limited = _rate_limited()
	if limited:
		return limited

	try:
		body = json.loads(frappe.request.get_data(as_text=True) or "{}")
	except ValueError:
		return _registration_error("invalid_client_metadata", "Body must be JSON.")
	if not isinstance(body, dict):
		return _registration_error("invalid_client_metadata", "Body must be a JSON object.")

	redirect_uris, problem = validate_redirect_uris(body.get("redirect_uris"))
	if problem:
		return _registration_error("invalid_redirect_uri", problem)

	grant_types = body.get("grant_types") or ["authorization_code"]
	if not isinstance(grant_types, list) or "authorization_code" not in grant_types:
		return _registration_error(
			"invalid_client_metadata", "grant_types must include authorization_code."
		)

	response_types = body.get("response_types") or ["code"]
	if not isinstance(response_types, list) or response_types != ["code"]:
		return _registration_error("invalid_client_metadata", 'response_types must be ["code"].')

	# RFC 7591 lets the server substitute a method it supports, and it says so in
	# the reply. Basic auth is not supported on v15, see AUTH_METHODS.
	auth_method = body.get("token_endpoint_auth_method")
	if auth_method not in AUTH_METHODS:
		auth_method = "client_secret_post"

	client_name = str(body.get("client_name") or "MCP Client").strip()[:120] or "MCP Client"

	client = frappe.get_doc(
		{
			"doctype": "OAuth Client",
			"app_name": f"{client_name} (MCP)",
			"redirect_uris": " ".join(redirect_uris),
			"default_redirect_uri": redirect_uris[0],
			"grant_type": "Authorization Code",
			"response_type": "Code",
			"scopes": " ".join(CLIENT_SCOPES),
			"skip_authorization": 0,
		}
	)
	client.insert(ignore_permissions=True)

	reply = {
		"client_id": client.client_id or client.name,
		"client_id_issued_at": int(frappe.utils.get_datetime(client.creation).timestamp()),
		"client_name": client_name,
		"redirect_uris": redirect_uris,
		"grant_types": ["authorization_code", "refresh_token"],
		"response_types": ["code"],
		"token_endpoint_auth_method": auth_method,
		"scope": " ".join(CLIENT_SCOPES),
	}
	if auth_method != "none":
		reply["client_secret"] = client.client_secret
		reply["client_secret_expires_at"] = 0
	return _json(reply, 201)


def validate_redirect_uris(value) -> tuple[list[str], str | None]:
	"""Check redirect URIs from a registration request.

	https anywhere, plain http only on loopback (desktop and CLI clients listen
	on a local port). Nothing else: no javascript:, data: or custom schemes, no
	fragments, and no whitespace, since Frappe stores the list space separated.
	"""

	if not isinstance(value, list) or not value:
		return [], "redirect_uris must be a non-empty list."
	if len(value) > MAX_REDIRECT_URIS:
		return [], f"At most {MAX_REDIRECT_URIS} redirect_uris."

	uris = []
	for uri in value:
		if not isinstance(uri, str) or not uri:
			return [], "Each redirect URI must be a non-empty string."
		if len(uri) > MAX_REDIRECT_URI_LENGTH:
			return [], f"Redirect URI longer than {MAX_REDIRECT_URI_LENGTH} characters: {uri[:60]}..."
		if any(ch.isspace() for ch in uri):
			return [], f"Redirect URI contains whitespace: {uri}"
		parsed = urlparse(uri)
		if parsed.fragment:
			return [], f"Redirect URI must not have a fragment: {uri}"
		if not parsed.hostname:
			return [], f"Redirect URI has no host: {uri}"
		if parsed.scheme == "https":
			pass
		elif parsed.scheme == "http" and parsed.hostname in LOOPBACK_HOSTS:
			pass
		else:
			return [], f"Redirect URI must be https, or http on localhost: {uri}"
		if uri not in uris:
			uris.append(uri)
	return uris, None


# ── helpers ──────────────────────────────────────────────────────────────────
def server_url() -> str:
	"""The site origin, worked out the way Frappe's own openid-configuration
	does, so the issuer here and there always agree."""

	base = frappe.get_value("Social Login Key", "frappe", "base_url")
	if base:
		return base.rstrip("/")
	url = urlparse(frappe.request.url)
	return f"{url.scheme}://{url.netloc}"


def _rate_limited():
	"""20 registrations per IP per hour. Returns an error Response, or None."""

	ip = frappe.local.request_ip or "unknown"
	key = frappe.cache.make_key(f"synapse:dcr:{ip}")
	count = frappe.cache.incrby(key, 1)
	if count == 1:
		frappe.cache.expire(key, 3600)
	if count > 20:
		return _registration_error("rate_limited", "Too many registrations from this address.", 429)
	return None


def _registration_error(code: str, description: str, status: int = 400):
	return _json({"error": code, "error_description": description}, status)


def _json(payload: dict, status: int = 200) -> Response:
	response = Response(json.dumps(payload), status=status, mimetype="application/json")
	response.headers["Cache-Control"] = "no-store"
	# Browser-based clients such as MCP Inspector fetch these cross-origin.
	response.headers["Access-Control-Allow-Origin"] = "*"
	return response
