# whetstone

A small workshop of [Claude Code](https://code.claude.com) tools to keep your craft sharp.

| Tool | Type | What it does |
|------|------|--------------|
| **cms** | skill + hook | Context Management System — standardizes docs across repos for AI-agent token efficiency. Frontmatter linting, ADR scaffolding, drift detection, staleness-based archival. Enforces frontmatter on `docs/*.md` edits via a `PreToolUse` hook. |
| **grill-me** | skill | Adversarial sparring partner — stress-tests a decision/plan before you commit (assumption audit, pre-mortem, outside view, falsifiable tripwires). |
| **develop** | command | A structured development workflow — classify → research → architect → implement → QA → docs → completion, with gates between phases. |

## Install

```
/plugin marketplace add Swissbit92/whetstone
/plugin install whetstone@whetstone
```

Then the tools are namespaced under the plugin:

- `/whetstone:cms` — run any CMS command (see the skill for subcommands)
- `/whetstone:grill-me` — start a grilling session
- `/whetstone:develop` — run the development workflow

`cms` and `grill-me` are also model-invoked: Claude triggers them automatically when their description matches what you're doing (editing docs, validating a decision).

## What's portable, what to adapt

- **grill-me** — fully generic, works out of the box.
- **cms** — generic engine. The `PreToolUse` hook gates `docs/*.md` edits. By
  default it scopes to the **current working directory**; set `CMS_ROOTS`
  (OS-path-separated list) to gate a fixed set of repos instead. Drift facts
  live in `state/sync_facts.yaml` and ship empty — add your own.
- **develop** — the workflow *structure* is generic; the per-repo specifics
  (critical-logic paths, test commands, alignment questions) are marked `<...>`
  for you to fill in. It uses a `qa-gatekeeper` agent if your project provides
  one, otherwise it does QA directly.

## cms state & persistence

CMS keeps a little state (CLAUDE.md size history, drift facts). Plugin updates
overwrite the cached plugin dir, so state resolves in this order:

1. `CMS_STATE_DIR` (explicit override)
2. `${CLAUDE_PLUGIN_DATA}/cms-state` (persists across plugin updates)
3. `<plugin>/skills/cms/state/` (local fallback)

## Requirements

- Claude Code with plugin support
- Python 3.9+ on `PATH` as `python3` (cms scripts are pure stdlib — no pip installs)

## Layout

```
whetstone/
├── .claude-plugin/marketplace.json     # marketplace catalog
└── plugins/whetstone/
    ├── .claude-plugin/plugin.json      # plugin manifest + cms hook
    ├── skills/
    │   ├── cms/                         # SKILL.md + scripts/ + templates/ + state/
    │   └── grill-me/SKILL.md
    └── commands/develop.md
```

## License

MIT — see [LICENSE](LICENSE).
