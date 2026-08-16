---
description: "Scaffold and validate .forge/adapter.json — the map from this project's own editor and runtime commands onto the engine-neutral vocabulary the forge skills are written against."
allowed-tools: ["Read", "Write", "Edit", "Glob", "Grep", "Bash"]
---

# forge-init — declare what this project can be asked to do

A published plugin cannot ship your project's commands. The verbs that matter most — start a
session, drive input, dump a trace, capture a sheet — are implemented in *your* source under
names only you use. This command writes the mapping so the skills can reach them without
ever naming them.

**Detect; do not invent.** Every entry you write must correspond to a command that exists.
A plausible-looking guess is the worst outcome available here: it produces a call that runs
nothing and reports success.

## 1. Read the vocabulary

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/adapter.py" --vocabulary
```

Nine canonical verbs. Only `editor.compile` is required — everything else is optional, and
an unimplemented verb is a reported gap that becomes `could-not-check` at the gate, which is
an honest outcome. **Do not pad the file to look complete.**

## 2. Find what actually exists

Look, in this order, and cite what you found:

1. **A bridge the project already has** — a script or CLI it uses to talk to the editor.
   Check `CLAUDE.md`/`AGENTS.md` first; a project that has one almost always documents it.
2. **Commands registered by the project's own source.** Search for the attribute or
   registration call the project's tooling uses, and prefer a live listing (`--list`,
   `--help`, a `commands` subcommand) over any copy in a document — the roster generated
   from source cannot go stale.
3. **An MCP server or editor package**, if one is registered.

If there is no transport at all, say so and stop. A mapping with nothing behind it is worse
than no mapping.

## 3. Write the declaration

```json
{
  "engine": "unity",
  "transport": {
    "command": "node tools/bridge.mjs pipeline exec {verb} {json}"
  },
  "verbs": {
    "editor.compile": "recompile_scripts",
    "editor.logs": "get_console_logs",
    "session.start": "<this project's session-start command>",
    "capture.sheet": "<this project's capture command>"
  }
}
```

`{verb}` is substituted with the project's own command name and is **required** — without it
every verb would run the same command, failing by doing the wrong thing quietly. `{json}` is
optional and receives the shell-quoted payload.

Omit any verb the project does not implement. Leave it out; do not map it to something
approximate.

## 4. Validate, and prove one verb round-trips

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/adapter.py" --repo . --list
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/adapter.py" --repo . --resolve editor.compile
```

Then **run the resolved command** and confirm it does what the verb claims — by the state it
leaves behind, not by its return value. A mapping that has never been executed is a guess
with better formatting.

## 5. Report

State: the transport found and where; which verbs are implemented and which are not; which
evidence classes the gaps make unavailable. That last sentence is the useful one — it tells
`crucible:finish-branch` in advance what will come back `could-not-check`.
