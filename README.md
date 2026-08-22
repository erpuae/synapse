# Synapse

A permission-aware [MCP](https://modelcontextprotocol.io) server for Frappe and
ERPNext. It lets an LLM client read and write a site's data **as a real user,
under that user's own permissions**, over OAuth, with every call written to an
audit log.

```
POST https://<your-site>/api/method/synapse.mcp.handle_mcp
```

## Why another one

Most Frappe MCP servers run privileged and hand the model raw SQL or
`ignore_permissions` document access. That is fine for a personal sandbox and
unacceptable on a business system. Synapse takes the opposite position:

- **No `ignore_permissions`, anywhere.** Every tool runs as the calling user.
  DocType permissions, User Permissions, share rules and submit/cancel rights all
  apply, and writes go through `Document.insert`/`save`/`submit`/`cancel` so
  validations, hooks and workflows fire exactly as they do in the desk.
- **A second boundary above permissions**, because "this user may edit Sales
  Invoices in the desk" and "an agent holding this user's token may edit Sales
  Invoices" are different decisions.
- **Everything is logged**, including calls refused before they reach a tool.
- **No dependencies.** The MCP server is vendored, so `bench install-app` is the
  whole installation and `bench update` stays safe.

## Install

```bash
bench get-app https://github.com/erpuae/synapse
bench --site <your-site> install-app synapse
```

Then check where the site stands at any point:

```bash
bench --site <your-site> execute synapse.mcp_tools.check.report
```

It prints what is configured and what is missing, in the order it has to be
fixed. A fresh install is fully closed: nothing is reachable until you say so.

## Tools

| Tool | Action needed |
|---|---|
| `list_available_doctypes`, `describe_doctype` | read |
| `get_doc`, `get_value`, `get_list`, `get_count` | read |
| `create_doc`, `update_doc`, `set_value` | write |
| `submit_doc` | submit |
| `cancel_doc` | cancel |
| `delete_doc` | delete |
| `run_sql_query` | the `MCP SQL Reader` role — see below |

Dates are returned in the format set in MCP Settings, ISO by default. Writes
accept ISO or DD-MM-YYYY either way, so a read-modify-write round trip cannot
swap day and month.

Deliberately **not** exposed: `frappe.db.set_value` (skips validation and hooks —
the `set_value` tool loads and saves the document instead), arbitrary whitelisted
method execution, rename and amend.

## Four gates

Every call passes all four. They are independent, and the narrowest wins.

1. **Authentication.** The endpoint is closed to guests, so an unauthenticated
   POST is refused by the framework before any tool code runs.
2. **A role on the tool.** Document tools need `MCP Agent`, the SQL tool needs
   `MCP SQL Reader`. Without the role the tool is not even listed.
3. **The MCP access list** (MCP Settings), an allowlist or a denylist. For
   anything other than a read, the caller must also hold a role the site has
   granted that action to.
4. **Frappe's own permissions**, as described above.

Administrator is not exempt. It holds every role, so gates 2 and 3's role check
pass, but the DocType list still binds.

## Access Mode

**Allowlist** — nothing is reachable except the DocTypes listed, each with the
actions ticked. Fails closed; a new DocType stays unreachable until someone says
otherwise. This is the default, and a fresh install has an empty list, so nothing
is reachable at all.

**Denylist** — every DocType is reachable except the ones listed. The user's own
Frappe permissions become the working boundary, and the list carves out what no
agent should touch whatever its user may do. Each row blocks everything by
default; untick *Block Read* to leave a DocType readable but unchangeable.

Denylist is easier to live with on a full ERP. Its cost is that a new DocType
arrives reachable, so two sets are enforced in that mode whether or not anyone
lists them:

- **Never reachable**: OAuth Bearer Token, OAuth Authorization Code, OAuth
  Client, Token Cache, Social Login Key, Connected App, Webhook, Email Account,
  Integration Request, User Social Login, Access Log. Reading these is how a
  reader becomes a writer.
- **Read only, always**: DocType, DocField, DocPerm, Custom DocPerm, Custom
  Field, Property Setter, Server Script, Client Script, Print Format, Report,
  Role, Has Role, User, User Permission, System Settings, Workflow, Scheduled Job
  Type. An agent that can edit Custom DocPerm can grant itself anything.

In allowlist mode neither set applies — there the table is the only authority.

Child tables are never reachable directly; they are read and written through
their parent. Matching is case insensitive and the DocType name is canonicalised
against the site before the list is consulted, so `salary slip` cannot slip past
a row reading `Salary Slip`.

To fill a large allowlist without ticking hundreds of grid rows:

```bash
bench --site <your-site> execute synapse.mcp_tools.allowlist.grant_all --kwargs "{'dry_run': 1}"
bench --site <your-site> execute synapse.mcp_tools.allowlist.grant_all
bench --site <your-site> execute synapse.mcp_tools.allowlist.show
```

`grant_all` defaults to read only and applies the same two protected sets. If you
want everything reachable, denylist mode with an empty list says that more
honestly than 700 allowlist rows.

## Setting it up

**1. OAuth.** Frappe 16 publishes OAuth server metadata and supports dynamic
client registration, which is what lets an MCP client connect without an OAuth
Client record being made by hand. It is off by default. In **OAuth Settings**
turn on *Show Auth Server Metadata*, *Show Protected Resource Metadata* and
*Enable Dynamic Client Registration*. Synapse never changes these — they affect
the whole site's OAuth behaviour, not just MCP.

Be clear about what a token grants: a Frappe OAuth token is not scoped to MCP. It
authorises the whole `/api` surface as that user.

**2. Assign `MCP Agent`** to the user the agent will act as. Whoever
authenticates is the identity every tool runs as, so scope that user to what the
agent should see rather than using an Administrator.

**3. Fill in MCP Settings.** Tick *Enable MCP Endpoint*, choose *Access Mode*, and
fill in the list it shows. Reads work at this point. For writes, also tick
*Enable Write Tools* and grant the actions to specific roles in *Role
Permissions*; with that table empty the endpoint stays read-only whatever else is
set.

## Connecting a client

```bash
claude mcp add --transport http mysite https://<your-site>/api/method/synapse.mcp.handle_mcp
```

Then authenticate — a browser opens on the site's login. Any MCP client that
speaks Streamable HTTP with OAuth works the same way; in Claude Desktop it is
Settings → Connectors → Add custom connector with the same URL.

## Raw SQL — read this before enabling it

> `run_sql_query` bypasses Frappe's permission system completely. A user holding
> `MCP SQL Reader` can read every table on the site regardless of their DocType
> permissions. Grant it only to users who already have full database access.

It is off until *Enable Read-Only SQL Tool* is ticked, and it does not use the
DocType access list — it cannot, since it never names a DocType. Prefer
`get_list` and `get_doc`; reach for SQL only for a join or an aggregate they
cannot express. If an agent is reaching for SQL constantly, the document tools
are missing something it needs.

Two layers stand behind it:

1. **A read-only database user**, enforced by MariaDB, so a query that gets past
   the text filter still cannot write.
2. **`mcp_tools/guard.py`** — statement type, no comments, no stacked statements,
   a keyword blocklist, a table blocklist and a length cap. Text matching, so
   treat it as belt rather than braces.

Set up layer 1 per site. As MariaDB root:

```sql
CREATE USER 'mcp_ro'@'localhost' IDENTIFIED BY '<STRONG_PASSWORD>';
GRANT SELECT ON `<DB_NAME>`.* TO 'mcp_ro'@'localhost';
REVOKE FILE ON *.* FROM 'mcp_ro'@'localhost';
FLUSH PRIVILEGES;
```

Then in `site_config.json` (never in the repo):

```json
{
  "mcp_ro_db_user": "mcp_ro",
  "mcp_ro_db_password": "<STRONG_PASSWORD>"
}
```

**Without those keys the tool falls back to the site's own read-write connection,
rolling back after every query.** It works, but the guard becomes the only
boundary. On hosted platforms where a second database user is not possible, that
fallback is the only option — decide consciously before enabling SQL there.

Extend the table blocklist per site with `mcp_sql_blocked_tables` in
`site_config.json`. MariaDB only; `connection.py` raises `NotImplementedError`
on other backends.

## Audit

Every call writes an **MCP Access Log** row — success, refusal or error — with
the tool, user, how they authenticated, IP, document touched, row counts and
timing. Writes also record the submitted values and the before/after of each
changed field. Calls refused before the tool body runs (unknown tool, missing
role, arguments that do not fit) are logged too: an agent probing tools it has no
rights to is exactly what an audit trail is for.

**A call missing from the log entirely never reached the server.** If a tool
appears blocked and the log has nothing for it, the block is in the client, most
often its own tool-permission prompt. That is the first thing to check.

Rows are written with their own commit after any rollback, so a failed or refused
write still leaves its record. Readable and reportable by System Manager, not
creatable or editable from the desk. `reference_doctype` and `reference_name` are
Data rather than Link fields on purpose — an audit row must never block deletion
of what it records. A daily job drops rows past the retention window. Untick *Log
Field Values* if the data itself must not be duplicated into the log;
password-like fields are masked either way.

## Tests

```bash
bench --site <your-site> run-tests --app synapse
```

The access list, the SQL guard, the tool schemas and the value conversion import
nothing from frappe, so they also run without a site:

```bash
python -m unittest discover -s apps/synapse -p 'test_mcp_*.py'
```

## Licence

GNU Affero General Public License v3.0 or later. See [LICENSE](LICENSE).

AGPL is deliberate: if you run a modified Synapse as a network service, the
people using it are entitled to your changes.
