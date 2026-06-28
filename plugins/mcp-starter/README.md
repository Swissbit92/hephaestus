# mcp-starter

A minimal, working template for shipping a **Python MCP server as a Claude Code plugin** —
and the documented packaging patterns behind it. Install it to see a two-tool example
server run, or copy it to start your own.

## What you get

```
mcp-starter/
├── .claude-plugin/plugin.json   # manifest: userConfig + INLINE mcpServers + first-run hook
├── commands/setup.md            # /mcp-starter:setup wizard (copy this pattern)
├── hooks/first-run.sh           # one-time install nudge (sentinel pattern)
└── servers/example/             # self-contained uv project — no system Python/pip
    ├── pyproject.toml           # [project.scripts] entry point
    └── example_server/
        ├── __init__.py
        └── server.py            # FastMCP server: ping + whoami (config-injection demo)
```

## The packaging patterns (why it's built this way)

### 1. Declare MCP servers INLINE in `plugin.json` — not a separate `.mcp.json`

```json
"mcpServers": {
  "example": {
    "command": "uv",
    "args": ["run", "--directory", "${CLAUDE_PLUGIN_ROOT}/servers/example", "example-server"],
    "env": { "EXAMPLE_API_KEY": "${user_config.api_key}" }
  }
}
```

Claude Code's plugin installer **skips dot-files/dot-directories** when copying from its
cache, so a `.mcp.json` can go missing after `/plugin update`. Declaring servers inline in
`plugin.json` (not a dot-file) means they **survive updates** with no manual cache patching.

### 2. Credential injection via `userConfig` + `${user_config.X}`

Declare fields in `userConfig`; map them into the server's environment in `mcpServers.env`.
Users fill them via `/plugin configure <plugin>` — no shell-profile editing required. The
server reads them as ordinary env vars (`os.environ["EXAMPLE_API_KEY"]`).

**Resolution order** to document for your users: plugin config (`/plugin configure`) →
shell environment → built-in default.

### 3. Self-contained `uv` server

Each server is its own `uv` project (`pyproject.toml` + a `[project.scripts]` entry point),
launched with `uv run --directory ${CLAUDE_PLUGIN_ROOT}/servers/<name> <entry>`. No system
Python or `pip install` — `uv` resolves the environment on first run. Requires
[`uv`](https://docs.astral.sh/uv/) on PATH.

### 4. First-run sentinel hook

`hooks/first-run.sh` writes a sentinel under `${CLAUDE_PLUGIN_DATA}` and prints a one-time
hint, then never fires again. It only writes to stdout (into Claude's context) — it cannot
break a session.

### 5. A `/setup` wizard command

`commands/setup.md` walks the user through prerequisites → config → restart → verify. Keep
it short; make the happy path zero-config where you can.

### Operational gotcha to tell users

**Config changes require a full Claude Code restart**, not `/reload-plugins` — MCP server
processes only re-read configuration on a fresh start.

## Install (try the example)

```
/plugin marketplace add Swissbit92/hephaestus
/plugin install mcp-starter@hephaestus
/mcp-starter:setup
```

Then call `ping` (→ `pong`) and `whoami` (→ whether the demo config was injected).

## Make your own

See `commands/setup.md` Step 4 for the rename checklist (server dir, package name,
`pyproject.toml`, `plugin.json` keys + paths, marketplace registration). For a full
real-world example built on these patterns, see the **sqlite-readonly** plugin in this repo.

## License

MIT.
