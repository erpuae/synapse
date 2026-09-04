# Copyright (c) 2026, Dxbitz and contributors
"""Short-lived read-only database connection for the MCP SQL tool.

The real security boundary. A separate MariaDB user holding nothing but SELECT
cannot write, drop or read files no matter what gets past guard.py, because the
database refuses it rather than a regex.

Set up per site, credentials in site_config.json (never in the repo):

	{
	  "mcp_ro_db_user": "mcp_ro",
	  "mcp_ro_db_password": "..."
	}

If those keys are absent the tool falls back to frappe.db.sql with a rollback,
and guard.py becomes the only boundary. That is a materially weaker posture -
see the SQL section of the app README.
"""

import contextlib

CONFIG_USER_KEY = "mcp_ro_db_user"
CONFIG_PASSWORD_KEY = "mcp_ro_db_password"
CONNECT_TIMEOUT = 5


def is_configured() -> bool:
	"""True when this site has read-only database credentials to connect with."""
	import frappe

	return bool(frappe.conf.get(CONFIG_USER_KEY) and frappe.conf.get(CONFIG_PASSWORD_KEY))


@contextlib.contextmanager
def read_only_cursor(timeout_seconds: int):
	"""Yield a dict cursor on a fresh read-only connection, closed on exit.

	The statement timeout is set on the session so a runaway join is killed by
	the server rather than holding a worker for the length of the HTTP request.
	"""
	import frappe
	import pymysql
	import pymysql.cursors

	if frappe.conf.get("db_type") not in (None, "mariadb"):
		# Only MariaDB is wired up here. Postgres needs `SET LOCAL
		# statement_timeout` and a psycopg connection; add it when a site needs it.
		raise NotImplementedError("The read-only MCP connection supports MariaDB only.")

	kwargs = {
		"user": frappe.conf.get(CONFIG_USER_KEY),
		"password": frappe.conf.get(CONFIG_PASSWORD_KEY),
		"database": frappe.conf.get("db_name"),
		"charset": "utf8mb4",
		"cursorclass": pymysql.cursors.DictCursor,
		"connect_timeout": CONNECT_TIMEOUT,
		"autocommit": True,
	}

	if socket := frappe.conf.get("db_socket"):
		kwargs["unix_socket"] = socket
	else:
		kwargs["host"] = frappe.conf.get("db_host") or "127.0.0.1"
		kwargs["port"] = int(frappe.conf.get("db_port") or 3306)

	connection = pymysql.connect(**kwargs)
	try:
		with connection.cursor() as cursor:
			# MariaDB takes seconds (as a double) on max_statement_time.
			cursor.execute("SET SESSION max_statement_time = %s", (float(timeout_seconds),))
			yield cursor
	finally:
		connection.close()
