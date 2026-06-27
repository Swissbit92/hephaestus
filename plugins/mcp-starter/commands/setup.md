---
name: setup
description: Verify the mcp-starter example server and explain how to copy it into your own MCP plugin.
user-invocable: true
---

# mcp-starter setup

## Step 1 — Prerequisite: `uv`

```bash
command -v uv && uv --version || echo "uv NOT found — install: https://docs.astral.sh/uv/"
```

## Step 2 — (Optional) set the demo config

Run `/plugin configure mcp-starter` and set **Example API key** to anything, to see config
injection in action. Then **restart Claude Code** (MCP servers read config only at startup).

## Step 3 — Verify

Call the tools and report results:
- `ping` → `pong` (server is alive)
- `whoami` → `{ "api_key_configured": true|false }` (true if you set the demo config and
  restarted)

## Step 4 — Make it your own

Copy `plugins/mcp-starter` to `plugins/<your-plugin>` and:
1. Rename the server dir `servers/example` → `servers/<your-server>`, the package
   `example_server` → `<your_package>`, and update `pyproject.toml` (`name`,
   `[project.scripts]`, `[tool.hatch...packages]`).
2. In `.claude-plugin/plugin.json`: rename the plugin, the `mcpServers` key, the
   `--directory` path, and map your real `userConfig` fields to env vars.
3. Replace the tools in `server.py` with yours.
4. Register the plugin in the repo's `.claude-plugin/marketplace.json`.

See this plugin's README for the packaging rationale (inline servers, the dotfile gotcha,
credential resolution, restart behavior).
