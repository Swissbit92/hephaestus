# hephaestus — repo guide

A public [Claude Code](https://code.claude.com) **marketplace** of small, sharp plugins.
This file orients contributors and AI agents working in this repo.

## What this is

A multi-plugin marketplace. Each plugin lives under `plugins/<name>/` with its own
`.claude-plugin/plugin.json`, versions independently, and is listed in
`.claude-plugin/marketplace.json`.

| Plugin | Scope |
|--------|-------|
| **crucible** | Generic, vendor-neutral craft tools: `cms`, `spar-with-me`, `grill-me`, `develop`, `start-branch`, `finish-branch`, `qa-gatekeeper`, `author-skill`, `session-to-skill`, `eval-first`, `flag-gate`, `loop-harness`, `act-for-real`, `repo-audit`, `refactor-audit` |
| **sqlite-readonly** | Zero-config read-only SQLite MCP server (3-layer read-only, NL→SQL) |
| **mcp-starter** | Template for packaging a Python MCP server as a plugin |
| **second-brain** | Obsidian inbox processor (suggest-then-confirm; skills-only) |
| **deck-builder** | Code-backed .pptx deck builder (python-pptx; outline-approval gate) |

## Branch model (read before starting work)

- **Integration branch:** `dev`. Feature work branches off it and merges back into it.
- **Release branch:** `main`. It is always releasable, and it is what the installed
  marketplace clone tracks — so anything merged here changes the tooling every session on
  this machine loads. That is the reason for the extra hop: `dev` is where work lands,
  `main` is where it is published.
- **Work happens on short-lived feature branches** named Conventional-Branch style:
  `<type>/<short-description>` in kebab-case — `feature/…`, `bugfix/…`, `hotfix/…`, `chore/…`.
- **Integrate via merge or PR into `dev`.** Never commit feature work directly to `dev` or
  `main`. Promote `dev` → `main` as a separate, deliberate step once the work is verified
  **on the merged tree** — a branch that passes alone and a merge that passes are different
  claims, and `main` moving underneath a long-lived branch is not hypothetical here.
- Tags are per-plugin: `<plugin>-v<x.y.z>` (e.g. `crucible-v0.2.0`), cut from `main`.

> The `start-branch` / `finish-branch` skills detect this model from this file — keep the
> section above accurate.

## Tests

Pure-stdlib Python; `pytest` from the repo root:

```bash
pytest -q                 # run the suite
pytest --collect-only -q  # count tests (baseline check)
```

Tests live in `tests/`. The `cms` scripts, the eval-harness core, and the `loop-harness`
scripts (budget/ledger/safety-hook/logscan/sweep) are the main code under test.

### Running on Windows and macOS

The suite and every script are expected to pass on Linux, macOS **and** Windows, and CI
enforces that in the `cross-platform` job. Three rules keep it that way, each written
after a defect that was invisible from a POSIX machine:

- **Never spell an interpreter `python3` in code.** Use `sys.executable`. On Windows that
  name resolves to a Microsoft Store stub which prints an ad, runs nothing and exits 49 —
  and `shutil.which()` cannot tell it apart from a real interpreter. Shell scripts source
  `scripts/checks/_python.sh`, which probes candidates by executing them and honours a
  `$PYTHON` override.
- **Pin encodings at both ends.** `subprocess(..., text=True)` decodes with the locale
  (cp1252 on many Windows installs), and `print()` encodes with the console codepage — the
  latter once made a *passing* gate exit 1 for printing a check-mark. Pass
  `encoding="utf-8", errors="replace"` to subprocess, and call `_utf8_stdio()` in `main()`.
- **Emit paths with `as_posix()`.** A path that lands in JSON, in a gate command or in a
  test comparison must use forward slashes; a backslash is also a shell escape.

## Skill-eval harness

`evals/` measures whether the plugins actually behave as their `SKILL.md` specifies —
deterministic-first (asserts git/file state + tool-call traces against throwaway fixtures),
with an optional pinned-Claude rubric judge. The pure core is unit-tested headless; the live
runner drives the `claude` CLI.

```bash
python3 evals/run_evals.py          # run the behavioral scenarios (needs the claude CLI)
```

See [evals/README.md](evals/README.md). Add a behavioral scenario whenever a skill makes a
new falsifiable claim.

## Secret-guard rule (non-negotiable)

This repo is **public** (ADR-002, currently on `main` only — see the note in
[docs/ROADMAP.md](docs/ROADMAP.md)), which makes this rule stricter rather than looser:
it must contain **zero** references to
any employer/secret system (the generic plugins were extracted clean-room from a private
fork), and publication means a leak cannot be walked back. Before every commit and as a
release precondition, run:

```bash
scripts/check-public-safe.sh
```

It fails on private-system tokens (the canonical list is the `PATTERN` in that script —
internal product names, employer names, internal hostnames, etc.). A non-zero exit blocks
the change. If you are porting a pattern from a private source, re-author it clean —
patterns in, private content out.

## Development workflow (dogfood)

We build hephaestus *using* crucible. For non-trivial work:

1. `develop` — classify (FULL / LIGHT / TRIVIAL) and run the matching phases.
2. `start-branch` (FULL/LIGHT) — isolate on a feature branch before touching code.
3. Implement → QA (tests green, no regression, `check-public-safe.sh` clean) → docs.
4. `finish-branch` (FULL/LIGHT) — test-gated merge/PR + safe cleanup.

Do **not** push or cut a release without an explicit go from the maintainer.

## Layout

```
hephaestus/
├── .claude-plugin/marketplace.json   # marketplace catalog (lists all plugins)
├── scripts/
│   ├── release.sh                    # per-plugin version bump + tag + GitHub release
│   ├── bump_version.py               # semver math (used by release.sh; unit-tested)
│   ├── validate_manifests.py         # marketplace + plugin manifest agreement (CI gate)
│   ├── check-public-safe.sh          # private-token guard
│   └── checks/                       # the executable half of docs/INVARIANTS.md
│       └── _python.sh                # sourced: resolves a Python that actually runs
├── evals/                            # skill-eval harness (behavioral scenarios; see its README)
├── tests/                            # pytest suite (cms + eval core + loop-harness under test)
├── CLAUDE.md                         # this file
├── CONTRIBUTING.md
└── plugins/
    ├── crucible/
    │   ├── .claude-plugin/plugin.json
    │   ├── skills/{cms,spar-with-me,grill-me,start-branch,finish-branch,author-skill,session-to-skill,eval-first,flag-gate,loop-harness,act-for-real,repo-audit,refactor-audit}/
    │   ├── scripts/                 # detect_profile · coverage_delta · invariants_run · new_skill · skill_lint (+ hook)
    │   ├── commands/develop.md
    │   └── agents/qa-gatekeeper.md
    ├── sqlite-readonly/         # read-only SQLite MCP server (uv project under servers/)
    ├── mcp-starter/             # MCP-plugin packaging template
    ├── second-brain/            # Obsidian inbox processor (suggest-then-confirm; skills-only)
    └── deck-builder/            # code-backed .pptx deck builder (python-pptx)
```

## Conventions

- Plugin code stays vendor-neutral and self-contained (the `cms` scripts are pure stdlib —
  no pip installs).
- Every release bumps the plugin's `version` in `plugin.json` (the pin is what triggers
  updates for installed users) — use `scripts/release.sh`.
- Markdown under a `docs/` dir carries cms frontmatter; root files (README, CLAUDE,
  CHANGELOG, CONTRIBUTING) do not.
