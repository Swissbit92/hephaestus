---
name: setup
description: First-time setup for sqlite-readonly — checks prerequisites, optionally points the server at your own database, and verifies the connection.
user-invocable: true
---

# sqlite-readonly setup

Walk through these steps in order. The server works with **zero config** against a bundled
sample database, so you can stop after Step 3 if you just want to try it.

## Step 1 — Prerequisite: `uv`

```bash
command -v uv && uv --version || echo "uv NOT found — install: https://docs.astral.sh/uv/ (brew install uv)"
```

If missing, install `uv`, then continue. (It runs the server in an isolated environment —
no system Python or pip changes.)

## Step 2 — (Optional) point at your own database

Zero-config uses a bundled sample DB. To serve your own:

> Run `/plugin configure sqlite-readonly` and set **SQLite database path** to the absolute
> path of a `.db` file (e.g. `/Users/me/data/app.db`). Leave it empty to keep the sample.

The file is opened **read-only** — the server can never modify it.

## Step 3 — Restart, then verify

Restart Claude Code (MCP servers pick up config only on a full restart — `/reload-plugins`
is not enough). Then call the `health_check` tool and report the result:

- `status: healthy`, `mode: sample` → running on the bundled sample DB.
- `status: healthy`, `mode: configured` → running on your DB at the shown path.

Then try it:
- `list_tables`
- `describe_table` on one of them
- `read_query` with `SELECT * FROM <table> LIMIT 5`
- `natural_language_query` with a plain-English question (uses your host model to write the SQL)

## Troubleshooting

| Symptom | Fix |
|---|---|
| Server missing from `/mcp` | `uv` not on PATH when Claude Code started, or a bad `SQLITE_DB_PATH`. Fix, then **full restart**. |
| `unable to open database file` | The path doesn't exist or isn't readable. SQLite `mode=ro` requires the file to already exist. |
| Config change had no effect | MCP servers only re-read config on a full restart — not `/reload-plugins`. |
| A write query returns an error | Working as intended — this server is read-only at three layers. |
