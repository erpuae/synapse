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
  Invoices" are different decisions. That boundary is the **Synapse Profile**.
- **Everything is logged**, including calls refused before they reach a tool.
- **No dependencies, and no roles of its own.** The MCP server is vendored, so
  `bench install-app` is the whole installation and `bench update` stays safe.

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
fixed. A fresh install is fully closed: no profile exists, so nothing is
reachable until you make one.

## Tools

| Tool | Action needed |
|---|---|
| `list_available_doctypes`, `describe_doctype` | read |
| `get_doc`, `get_value`, `get_list`, `get_count` | read |
| `create_doc`, `update_doc`, `set_value` | write |
| `add_child`, `set_child_value`, `delete_child` | write |
| `replace_in_field` | write |
| `submit_doc` | submit |
| `cancel_doc` | cancel |
| `delete_doc` | delete |
| `run_operation` | operate |
| `run_sql_query` | a profile with **Allow SQL** — see below |

The child-table tools edit one row of a table in place, instead of `update_doc`
replacing the whole table (which means resending every row to change one).
`replace_in_field` edits part of a long text field and refuses unless the text
it is asked to find occurs exactly the number of times the caller expected, so
it can never quietly rewrite the wrong span. `run_operation` calls a document's
own method — see **The operate action** below.

Dates are returned in the format set in Synapse Settings, ISO by default. Writes
accept ISO or DD-MM-YYYY either way, so a read-modify-write round trip cannot
swap day and month.

Deliberately **not** exposed: `frappe.db.set_value` (skips validation and hooks —
the `set_value` tool loads and saves the document instead), rename and amend.

## Three gates

Every call passes all three. They are independent, and the narrowest wins.

1. **Authentication.** The endpoint is closed to guests, so an unauthenticated
   POST is refused by the framework before any tool code runs.
2. **The Synapse access model.** A **Synapse Profile** whose roles the caller
   holds must grant the DocType and the action, and the site backstop must not
   take it back. See below.
3. **Frappe's own permissions**, as described above. Every tool operates as the
   session user with permissions on.

Synapse creates no roles. Whoever authenticates is the identity every tool runs
as, so scope that user — and the profiles their roles fall under — to what the
agent should see rather than using an Administrator.

## Synapse Profiles

Access is granted by **Synapse Profile** records. A profile lists some **roles**
and the **DocTypes and actions** those roles may reach through the endpoint. A
user's reach is the **union of every enabled profile whose roles they hold**.

- With no matching profile, nothing is reachable — a fresh install is closed.
- A tick in a profile is a ceiling, not a grant: the user still needs the
  matching Frappe permission on the record, checked when the document is touched.
- **Full Access** on a profile grants every action on every DocType, ignoring the
  grid. The user's own Frappe permissions — already the boundary you scoped —
  become the working limit. It is a deliberate choice, made per profile, not a
  default.
- **Allow SQL** on a profile turns on the raw SQL tool for its users. Read the
  SQL section before ticking it.

Above every profile sits a site-wide **backstop** in Synapse Settings, and two
built-in sets that apply whether or not anyone lists them:

- **Never reachable**: OAuth Bearer Token, OAuth Authorization Code, OAuth
  Client, Token Cache, Social Login Key, Connected App, Webhook, Email Account,
  Integration Request, User Social Login, Access Log, and Synapse's own control
  plane (Settings, Profile and Log). Reading these is how a reader becomes a
  writer, or rewrites the gate that governs it.
- **Read only, always**: DocType, DocField, DocPerm, Custom DocPerm, Custom
  Field, Property Setter, Server Script, Client Script, Print Format, Report,
  Role, Has Role, User, User Permission, System Settings, Workflow, Scheduled Job
  Type. An agent that can edit Custom DocPerm can grant itself anything.

The **Blocked DocTypes** table in Synapse Settings is the site-wide part of the
backstop: carve-outs that no profile can override, for the things no agent should
touch whatever its user may do. Each row blocks everything by default; untick
*Block Read* to leave a DocType readable but unchangeable.

Child tables are never reachable directly; they are read and written through
their parent. Matching is case insensitive and the DocType name is canonicalised
against the site before the profiles are consulted, so `salary slip` cannot slip
past a grant reading `Salary Slip`.

To fill a large profile without ticking hundreds of grid rows:

```bash
bench --site <your-site> execute synapse.mcp_tools.profiles.grant_all \
  --kwargs "{'profile': 'Reporting', 'actions': 'read', 'dry_run': 1}"
bench --site <your-site> execute synapse.mcp_tools.profiles.grant_all \
  --kwargs "{'profile': 'Reporting', 'actions': 'read'}"
bench --site <your-site> execute synapse.mcp_tools.profiles.show \
  --kwargs "{'profile': 'Reporting'}"
```

`grant_all` defaults to read only and applies the same two protected sets. If you
want everything reachable, tick Full Access on the profile — it says that in one
box rather than 700 rows, and it stays correct as the schema grows.

## The operate action

`run_operation` calls a document's **own method** by name — the behaviour a desk
button triggers, like a Sales Invoice reposting its accounting entries. It is the
one tool with the reach of arbitrary code, so it has its own action, **operate**,
granted per DocType in a profile. That grant is the allowlist that makes it safe
to expose: a profile has to say, for this DocType, that operations may run.

It still runs as the calling user, under Frappe permissions, and is fully logged.
Methods that have their own dedicated, gated tool (`save`, `submit`, `cancel`,
`delete` …) are refused here, and so is anything private, so operate can never be
a side door around the other gates.

## The model provider

Synapse Settings carries a **Model Provider** choice. Only Claude is wired up;
the other options are placeholders that change nothing about how tools run. The
setting records which model family the site presents Synapse for. Support beyond
Claude is not implemented yet.

## Setting it up

**1. OAuth.** Frappe 16 publishes OAuth server metadata and supports dynamic
client registration, which is what lets an MCP client connect without an OAuth
Client record being made by hand. It is off by default. In **OAuth Settings**
turn on *Show Auth Server Metadata*, *Show Protected Resource Metadata* and
*Enable Dynamic Client Registration*. Synapse never changes these — they affect
the whole site's OAuth behaviour, not just MCP.

Be clear about what a token grants: a Frappe OAuth token is not scoped to MCP. It
authorises the whole `/api` surface as that user.

**2. Create a Synapse Profile.** Add the roles the agent's user holds, and the
DocTypes and actions those roles may reach. Reading needs only a read tick.

**3. Fill in Synapse Settings.** Tick *Enable Synapse Endpoint* and *Enable Read
Tools*. Reads work at this point. For writes, also tick *Enable Write Tools*;
with that switch off the endpoint stays read-only whatever a profile grants.

## Connecting a client

```bash
claude mcp add --transport http mysite https://<your-site>/api/method/synapse.mcp.handle_mcp
```

Then authenticate — a browser opens on the site's login. Any MCP client that
speaks Streamable HTTP with OAuth works the same way; in Claude Desktop it is
Settings → Connectors → Add custom connector with the same URL.

## Raw SQL — read this before enabling it

> `run_sql_query` bypasses Frappe's permission system completely. A user in a
> profile with **Allow SQL** can read every table on the site regardless of their
> DocType permissions. Grant it only to users who already have full database
> access.

It is off until *Enable Read-Only SQL Tool* is ticked in Synapse Settings **and**
the caller holds a profile with *Allow SQL*. It does not use the profile's
DocType grants — it cannot, since it never names a DocType. Prefer `get_list` and
`get_doc`; reach for SQL only for a join or an aggregate they cannot express. If
an agent is reaching for SQL constantly, the document tools are missing something
it needs.

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

Every call writes a **Synapse Log** row — success, refusal or error — with the
tool, user, how they authenticated, IP, document touched, row counts and timing.
Writes also record the submitted values and the before/after of each changed
field. Calls refused before the tool body runs (unknown tool, arguments that do
not fit) are logged too: an agent probing tools it has no rights to is exactly
what an audit trail is for.

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

The access model, the SQL guard, the tool schemas and the value conversion
import nothing from frappe, so they also run without a site:

```bash
python -m unittest discover -s apps/synapse -p 'test_mcp_*.py'
```

## Licence

GNU Affero General Public License v3.0 or later. See [LICENSE](LICENSE).

AGPL is deliberate: if you run a modified Synapse as a network service, the
people using it are entitled to your changes.
