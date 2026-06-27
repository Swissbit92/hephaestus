#!/usr/bin/env bash
# First-run nudge for sqlite-readonly. Writes a sentinel once, prints a one-time hint,
# never runs again. Pure stdout into Claude's context — it cannot break the session.
set -euo pipefail

SENTINEL="${CLAUDE_PLUGIN_DATA:-$HOME/.claude/plugins/data/sqlite-readonly}/setup-complete"
if [ ! -f "$SENTINEL" ]; then
  mkdir -p "$(dirname "$SENTINEL")"
  touch "$SENTINEL"
  cat <<'MSG'
[sqlite-readonly] Installed. It works with zero config against a bundled sample database.
To point it at your own DB, run /sqlite-readonly:setup (sets SQLITE_DB_PATH), then restart
Claude Code. Requires `uv` (https://docs.astral.sh/uv/) on PATH.
MSG
fi
