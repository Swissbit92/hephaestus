# whetstone — repo guide

A public [Claude Code](https://code.claude.com) **marketplace** of small, sharp plugins.
This file orients contributors and AI agents working in this repo.

## What this is

A multi-plugin marketplace. Each plugin lives under `plugins/<name>/` with its own
`.claude-plugin/plugin.json`, versions independently, and is listed in
`.claude-plugin/marketplace.json`.

| Plugin | Scope |
|--------|-------|
| **whetstone** | Generic, vendor-neutral craft tools: `cms`, `grill-me`, `develop`, `start-branch`, `finish-branch`, `qa-gatekeeper`, `author-skill` |
| **sqlite-readonly** | Zero-config read-only SQLite MCP server (3-layer read-only, NL→SQL) |
| **mcp-starter** | Template for packaging a Python MCP server as a plugin |
| **second-brain** | Obsidian inbox processor (suggest-then-confirm; skills-only) |
| **deck-builder** | Code-backed .pptx deck builder (python-pptx; outline-approval gate) |

## Branch model (read before starting work)

- **Integration branch:** `main`. It is always releasable.
- **Work happens on short-lived feature branches** named Conventional-Branch style:
  `<type>/<short-description>` in kebab-case — `feature/…`, `bugfix/…`, `hotfix/…`, `chore/…`.
- **Integrate via merge or PR back into `main`.** Never commit feature work directly to `main`.
- Tags are per-plugin: `<plugin>-v<x.y.z>` (e.g. `whetstone-v0.2.0`).

> The `start-branch` / `finish-branch` skills detect this model from this file — keep the
> section above accurate.

## Tests

Pure-stdlib Python; `pytest` from the repo root:

```bash
pytest -q                 # run the suite
pytest --collect-only -q  # count tests (baseline check)
```

Tests live in `tests/`. The `cms` scripts are the main code under test.

## Public-safety rule (non-negotiable)

This is a **public** repo. It must contain **zero** references to any private/employer
system. Before every commit and as a release precondition, run:

```bash
scripts/check-public-safe.sh
```

It fails on private-system tokens (the canonical list is the `PATTERN` in that script —
internal product names, employer names, internal hostnames, etc.). A non-zero exit blocks
the change. If you are porting a pattern from a private source, re-author it clean —
patterns in, private content out.

## Development workflow (dogfood)

We build whetstone *using* whetstone. For non-trivial work:

1. `develop` — classify (FULL / LIGHT / TRIVIAL) and run the matching phases.
2. `start-branch` (FULL/LIGHT) — isolate on a feature branch before touching code.
3. Implement → QA (tests green, no regression, `check-public-safe.sh` clean) → docs.
4. `finish-branch` (FULL/LIGHT) — test-gated merge/PR + safe cleanup.

Do **not** push or cut a release without an explicit go from the maintainer.

## Layout

```
whetstone/
├── .claude-plugin/marketplace.json   # marketplace catalog (lists all plugins)
├── scripts/
│   ├── release.sh                    # per-plugin version bump + tag + GitHub release
│   ├── bump_version.py               # semver math (used by release.sh; unit-tested)
│   ├── new_skill.py                  # scaffold a new skill (used by author-skill)
│   └── check-public-safe.sh          # private-token guard
├── tests/                            # pytest suite (cms scripts under test)
├── CLAUDE.md                         # this file
├── CONTRIBUTING.md
└── plugins/
    ├── whetstone/
    │   ├── .claude-plugin/plugin.json
    │   ├── skills/{cms,grill-me,start-branch,finish-branch}/
    │   ├── commands/develop.md
    │   └── agents/qa-gatekeeper.md
    ├── sqlite-readonly/         # read-only SQLite MCP server (uv project under servers/)
    └── mcp-starter/             # MCP-plugin packaging template
```

## Conventions

- Plugin code stays vendor-neutral and self-contained (the `cms` scripts are pure stdlib —
  no pip installs).
- Every release bumps the plugin's `version` in `plugin.json` (the pin is what triggers
  updates for installed users) — use `scripts/release.sh`.
- Markdown under a `docs/` dir carries cms frontmatter; root files (README, CLAUDE,
  CHANGELOG, CONTRIBUTING) do not.
