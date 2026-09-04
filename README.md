# Synapse

Synapse is an [MCP](https://modelcontextprotocol.io) server for Frappe and
ERPNext. It lets an AI client read and write a site over OAuth. The client acts
as a real Frappe user and stays within that user's permissions. Every call is
written to an audit log.

```
POST https://<your-site>/api/method/synapse.mcp.handle_mcp
```

## What makes it different

Many Frappe MCP servers run with full privileges and give the model raw SQL or
document access with permissions turned off. That is fine for a personal
sandbox. It is not safe on a business system. Synapse works the other way.

- It never turns off permissions. Every tool runs as the signed in user.
  DocType permissions, User Permissions, share rules and submit or cancel rights
  all apply. Writes go through the normal insert, save, submit and cancel path,
  so validations, hooks and workflows run the same as they do in the desk.
- It adds a second layer above permissions. "This user may edit Sales Invoices
  in the desk" and "an AI agent holding this user's token may edit Sales
  Invoices" are two different decisions. That second decision is the Synapse
  Profile.
- It logs every call, including ones that are refused.
- It has no external dependencies and creates no roles. A plain
  `bench install-app` is the whole install.

## Install

```bash
bench get-app https://github.com/dxbitz-technology/synapse
bench --site <your-site> install-app synapse
```

Check the current state of a site at any time:

```bash
bench --site <your-site> execute synapse.mcp_tools.check.report
```

It prints what is set up and what is missing, in the order to fix it. A fresh
install is fully closed. Nothing is reachable until you create a profile.

## How access works

Access is granted by **Synapse Profile** records. A profile lists a set of roles
and the DocTypes and actions those roles may use. A user's access is the sum of
every enabled profile whose roles they hold.

- With no matching profile, nothing is reachable.
- A tick in a profile is a ceiling, not a grant. The user still needs the
  matching Frappe permission on the record. That is checked when the document is
  touched.
- **Full Access** on a profile grants every action on every DocType and ignores
  the grid. The user's own Frappe permissions become the working limit. Use it
  only for a user whose Frappe permissions are already scoped the way you want.
- **Allow SQL** on a profile turns on the raw SQL tool for its users. Read the
  SQL section first.

Two fixed rules sit above every profile and cannot be overridden:

- Some DocTypes are never reachable. These hold tokens, credentials and the
  records that hand them out, plus Synapse's own settings, profiles and log.
  Reading them is how a read-only user could turn into a writer, or edit the
  gate that controls them.
- Some DocTypes are read only and can never be written. These define the schema,
  the code and the permission model, for example DocType, Custom Field, Server
  Script, Custom DocPerm, Role and User. A user who could edit Custom DocPerm
  could grant themselves anything.

Synapse Settings also has a site wide **Blocked DocTypes** list. Use it to block
something that a profile would otherwise allow.

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
| `run_sql_query` | a profile with Allow SQL (see below) |

The child table tools edit one row of a table in place. Without them,
`update_doc` replaces the whole table, so you would have to send every row back
to change one. `replace_in_field` edits part of a long text field. It counts how
many times the text you want to change appears, and it refuses unless that count
matches the number you expected, so it cannot rewrite the wrong part by mistake.
`run_operation` runs a document's own method (see below).

Dates come back in the format set in Synapse Settings, ISO by default. Writes
accept ISO or DD-MM-YYYY, so a read then write round trip cannot swap the day and
the month.

## The operate action

`run_operation` runs a document's own method by name. This is the behaviour
behind a desk button, for example a Sales Invoice reposting its accounting
entries. Because it can run code, it has its own action, **operate**, which is
granted per DocType in a profile. That grant is what makes it safe to offer. A
profile has to say, for this DocType, that operations may run.

It still runs as the signed in user, under Frappe permissions, and every call is
logged. Methods that already have their own tool (save, submit, cancel, delete
and so on) are refused here, and so is anything private. So operate cannot be
used to get around the other tools.

## Model provider

Synapse Settings has a **Model Provider** choice. Claude is the only provider
that is wired up. The other options are placeholders. The setting records which
model family the site presents Synapse for and does not change how tools run.

## Setting it up

**1. OAuth.** Frappe 16 can publish OAuth server metadata and support dynamic
client registration. This is what lets an MCP client connect without someone
creating an OAuth Client record by hand. It is off by default. In **OAuth
Settings** turn on *Show Auth Server Metadata*, *Show Protected Resource
Metadata* and *Enable Dynamic Client Registration*. Synapse does not change these
settings. They affect the whole site's OAuth behaviour.

A Frappe OAuth token is not limited to MCP. It authorises the whole `/api`
surface as that user, so scope the user accordingly.

**2. Create a Synapse Profile.** Add the roles the agent's user holds, then the
DocTypes and actions those roles may use. Reading needs only a read tick.

**3. Fill in Synapse Settings.** Tick *Enable Synapse Endpoint* and *Enable Read
Tools*. Reads work at this point. For writes, also tick *Enable Write Tools*. If
that switch is off, the endpoint stays read only whatever a profile grants.

## Connecting a client

```bash
claude mcp add --transport http mysite https://<your-site>/api/method/synapse.mcp.handle_mcp
```

Then sign in. A browser opens on the site login page. Any MCP client that speaks
Streamable HTTP with OAuth works the same way. In Claude Desktop it is Settings,
Connectors, Add custom connector, with the same URL.

## Raw SQL

`run_sql_query` does not use Frappe's permission system. A user in a profile with
Allow SQL can read every table on the site, whatever their DocType permissions
are. Grant it only to users who already have full database access.

It is off until *Enable Read-Only SQL Tool* is ticked in Synapse Settings and the
user holds a profile with *Allow SQL*. It does not use the profile's DocType
grants, because it never names a DocType. Prefer `get_list` and `get_doc`. Use
SQL only for a join or an aggregate they cannot express. If an agent keeps
reaching for SQL, the document tools are probably missing something it needs.

Two layers protect it:

1. A read only database user, enforced by MariaDB. A query that gets past the
   text filter still cannot write.
2. `mcp_tools/guard.py`. It checks the statement type, blocks comments, blocks
   more than one statement, blocks a list of keywords and tables, and caps the
   length. This is text matching, so treat it as a backup, not the main line of
   defence.

Set up the database user per site. As MariaDB root:

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

Without those keys, the tool falls back to the site's normal read write
connection and rolls back after every query. It works, but then the text guard
is the only boundary. On hosted platforms where a second database user is not
possible, that fallback is the only option. Decide before you enable SQL there.

Add more blocked tables per site with `mcp_sql_blocked_tables` in
`site_config.json`. MariaDB only. `connection.py` raises `NotImplementedError` on
other backends.

## Audit

Every call writes a **Synapse Log** row: success, refusal or error. Each row
records the tool, the user, how they signed in, the IP address, the document
touched, the row counts and the timing. Writes also record the values sent and
the before and after of each changed field. Calls that are refused before the
tool runs are logged too.

If a tool looks blocked and there is no log row for it, the block is in the
client, usually its own tool permission prompt. Check that first.

Log rows are written with their own commit after any rollback, so a failed or
refused write still leaves a record. System Manager can read and report on the
log but cannot create or edit rows from the desk. A daily job drops rows past the
retention window. Untick *Log Field Values* if the data itself must not be copied
into the log. Password fields are masked either way.

## Tests

```bash
bench --site <your-site> run-tests --app synapse
```

The access model, the SQL guard, the tool schemas and the value conversion do
not import anything from frappe, so they also run without a site:

```bash
python -m unittest discover -s apps/synapse -p 'test_mcp_*.py'
```

## Licence

GNU Affero General Public License v3.0 or later. See [LICENSE](LICENSE).
