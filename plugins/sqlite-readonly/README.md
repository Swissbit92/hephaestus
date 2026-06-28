# sqlite-readonly

A zero-config, **read-only** SQLite MCP server for Claude Code. Point it at any local
`.db` file (or use the bundled sample) and query it safely — it cannot modify your data.

## Why read-only is real here (three layers)

1. **Connection** (primary): the database is opened with `mode=ro`, so SQLite refuses
   every write at the engine level — no tool can mutate data even if asked.
2. **Validator** (defense-in-depth): queries must be a single read-only statement
   (SELECT/WITH/EXPLAIN/VALUES/PRAGMA); write/DDL keywords and stacked statements are
   rejected before execution.
3. **Row cap**: every query is capped (default 100 rows) to avoid runaway scans.

## Tools

| Tool | What it does |
|------|--------------|
| `health_check` | Status, which DB is served, table count |
| `list_tables` | List user tables |
| `describe_table` | Columns (name, type, PK, not-null) for a table |
| `read_query` | Run one read-only SQL query → `{columns, rows, executed_sql}` |
| `natural_language_query` | Ask in plain English; the host model writes the SQL, which is then validated + run (generate→validate→retry) |

A `schema://main` resource exposes the schema as token-budgeted Markdown.

## Install

```
/plugin marketplace add Swissbit92/hephaestus
/plugin install sqlite-readonly@hephaestus
/sqlite-readonly:setup     # optional — works zero-config against a sample DB
```

Requires [`uv`](https://docs.astral.sh/uv/) on PATH. Each server runs in its own `uv`
project (no system Python/pip changes).

## Configuration

All optional — it runs zero-config against a bundled sample DB:

| Setting (env / plugin config) | Default | Meaning |
|---|---|---|
| `db_path` / `SQLITE_DB_PATH` | sample DB | Absolute path to a `.db` to serve read-only |
| `SQLITE_MAX_ROWS` | 100 | Result-set cap |
| `SQLITE_SCHEMA_TTL` | 3600 | Schema cache TTL (seconds) |
| `SQLITE_SCHEMA_TOKENS` | 2000 | Schema-context token budget |

Set `db_path` via `/plugin configure sqlite-readonly`, then **restart Claude Code**.

## Known issues / operational notes

- **MCP servers are declared inline in `plugin.json`** (not a separate `.mcp.json`). Claude
  Code's installer skips dot-files when copying from its cache, so a `.mcp.json` can go
  missing on `/plugin update`; inline `mcpServers` survive updates. (This is the packaging
  pattern the `mcp-starter` plugin documents.)
- **Config changes need a full restart**, not `/reload-plugins` — MCP server processes only
  re-read configuration on a fresh Claude Code start.
- **Credential/config resolution order** is: plugin config (`/plugin configure`) → shell
  environment → built-in default. (SQLite needs no credentials; `db_path` follows this.)
- **`mode=ro` requires the file to exist** — the server won't create a database.

## Layout

```
sqlite-readonly/
├── .claude-plugin/plugin.json   # manifest: userConfig + INLINE mcpServers + first-run hook
├── commands/setup.md            # /sqlite-readonly:setup wizard
├── hooks/first-run.sh           # one-time install nudge (sentinel)
└── servers/sqlite-readonly/     # self-contained uv project
    ├── pyproject.toml
    ├── sample.sql               # bundled sample DB source (zero-config default)
    └── sqlite_readonly/
        ├── validator.py         # read-only SQL validation + row cap
        ├── schema.py            # introspection + TTL cache + token-budgeted render
        ├── nl.py                # NL→SQL generate-validate-retry
        ├── db.py                # read-only connection + query path
        └── server.py            # FastMCP wrapper (the only module importing `mcp`)
```

## License

MIT.
