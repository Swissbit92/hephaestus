# whetstone

A small workshop of [Claude Code](https://code.claude.com) tools to keep your craft sharp.

| Tool | Type | What it does |
|------|------|--------------|
| **cms** | skill + hook | Context Management System — standardizes docs across repos for AI-agent token efficiency. Frontmatter linting, ADR scaffolding, drift detection, staleness-based archival. Enforces frontmatter on `docs/*.md` edits via a `PreToolUse` hook. |
| **grill-me** | skill | Adversarial sparring partner — stress-tests a decision/plan before you commit (assumption audit, pre-mortem, outside view, falsifiable tripwires). |
| **develop** | command | A structured development workflow — classify → research → architect → implement → QA → docs → completion, with gates between phases. |
| **qa-gatekeeper** | agent | Skeptical QA gate used by `develop`'s Phase 4 — verifies stated changes, hunts bugs/orphaned code, runs tests, and returns PASS / CONDITIONAL PASS / REJECT. |

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
  for you to fill in. Its Phase 4 uses the bundled **qa-gatekeeper** agent.
- **qa-gatekeeper** — generic; infers the project's test command from the repo.
  Augment its quality standards with your repo's CLAUDE.md.

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
    ├── commands/develop.md
    └── agents/qa-gatekeeper.md
```

## Releasing

The `version` in `plugin.json` is what triggers updates for installed users —
pushing commits without bumping it does nothing for them. Use the helper, which
keeps the manifest version and git tag in lockstep:

```bash
scripts/release.sh patch              # 0.1.0 -> 0.1.1
scripts/release.sh minor              # 0.1.0 -> 0.2.0
scripts/release.sh major              # 0.1.0 -> 1.0.0
scripts/release.sh 1.2.3              # explicit version
scripts/release.sh patch --dry-run    # preview, change nothing
```

It refuses to run unless you're on `main` with a clean tree, validates the
plugin, then commits, tags `vX.Y.Z`, pushes, and creates a GitHub release with
notes drawn from the commits since the last tag.

## License

MIT — see [LICENSE](LICENSE).
