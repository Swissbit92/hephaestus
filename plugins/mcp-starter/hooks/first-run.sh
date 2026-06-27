#!/usr/bin/env bash
# First-run nudge (sentinel pattern). Writes a marker once, prints a one-time hint, never
# runs again. Pure stdout into Claude's context — cannot break the session.
set -euo pipefail

SENTINEL="${CLAUDE_PLUGIN_DATA:-$HOME/.claude/plugins/data/mcp-starter}/setup-complete"
if [ ! -f "$SENTINEL" ]; then
  mkdir -p "$(dirname "$SENTINEL")"
  touch "$SENTINEL"
  cat <<'MSG'
[mcp-starter] Installed. This is a template — run /mcp-starter:setup to verify the example
server, then copy plugins/mcp-starter to start your own MCP plugin. Requires `uv` on PATH.
MSG
fi
