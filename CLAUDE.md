# hephaestus — repo guide

A public [Claude Code](https://code.claude.com) **marketplace** of small, sharp plugins.
This file orients contributors and AI agents working in this repo.

## What this is

A multi-plugin marketplace. Each plugin lives under `plugins/<name>/` with its own
`.claude-plugin/plugin.json`, versions independently, and is listed in
`.claude-plugin/marketplace.json`.

| Plugin | Scope |
|--------|-------|
| **crucible** | Generic, vendor-neutral craft tools: `cms`, `spar-with-me`, `grill-me`, `develop`, `start-branch`, `sync-branch`, `finish-branch`, `qa-gatekeeper`, `skill-craft`, `eval-first`, `flag-gate`, `loop-harness`, `act-for-real`, `repo-audit`, `refactor-audit` |
| **forge-unity** | Unity evidence + the `.forge/adapter.json` contract. Engine-specific but **operator-free** — it may name Unity, never a particular game ([ADR-003](docs/decisions/003-decompose-game-development-support-into-a-growing-crucible-and-one-thin-engine-adapter.md)) |
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
- **Never decide anything from a file's mtime in shipped plugin code.** git neither records
  nor restores modification times, so a clone stamps every file with the checkout time and
  any such rule reports every file as brand new the moment the repo moves machines — while
  looking healthy, because "no findings" is also what a clean repo looks like. `render.py`
  learned this, wrote it in its own docstring, and the archive rule then repeated it at four
  sites, one of which *persisted* a wrong date into frontmatter. Use the git committer date
  (`plugins/crucible/skills/cms/scripts/doc_age.py` is importable and already does the
  batching, shallow-clone detection and fallbacks) or a date carried in the file's content.
  Enforced by `scripts/mtime_guard.py`, which parses rather than greps — a textual search
  flags `doc_age.py`'s own docstring, and a rule that accuses its own fix gets switched off.
- **A check that cannot fail is not a check, and silence is not success.** Three defects
  this month shared one shape: the code was present, plausible, and quiet when wrong. Age
  from mtime worked locally and was dead on every clone; `predictions.py`'s `--check`
  refusal sat behind `required=True` so argparse answered first and the message was never
  once displayed; `sync.py` returned zero facts and exit 0 for any YAML outside its narrow
  subset, which reads exactly like "no drift". Before trusting a new gate, **reintroduce
  the defect and watch it go red** — that is what `--baseline` forces at record time and
  what `tests/test_mtime_guard.py` and `tests/test_sync_facts.py` pin permanently. Where a
  check genuinely cannot run, exit **2**; folding could-not-determine into 0 is how an
  unverified change acquires a green tick.
- **Do not exceed the Python floor the README promises (3.9).** A file that will not parse
  does not degrade one feature — it stops `pytest` collecting, so the suite is unavailable
  on that interpreter. Note that `ast.parse(feature_version=…)` **cannot** catch this alone:
  PEP 701 was a tokenizer change, so a 3.13 interpreter accepts 3.12-only f-strings whatever
  floor you request. `scripts/python_floor.py` runs three passes (grammar, f-string
  constructs, module-level stdlib imports) and CI runs the suite on 3.9–3.13.

### Cross-agent (Claude Code, Codex, Pi)

Claude Code consumes this repo as **plugins**; Codex and Pi discover **skill directories**.
So the portable subset is exactly the skills — slash commands, subagents, hooks and MCP
servers do not travel, and `scripts/install_skills.py` prints that gap rather than letting a
skill quietly lose its hook. Keep every `SKILL.md` inside the frontmatter set all three
honour (`name`, `description`, `disable-model-invocation`, `metadata`); `skill_lint.py`
warns on anything else.

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

This repo is **public**
([ADR-002](docs/decisions/002-publish-hephaestus-publicly-retiring-the-private-distribution-non-goal.md)),
which makes this rule stricter rather than looser: it must contain **zero** references to
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
   FULL records a falsifiable prediction before implementing and settles it at completion.
2. `start-branch` (FULL/LIGHT) — isolate on a feature branch before touching code.
3. Implement → QA (tests green, no regression, `check-public-safe.sh` clean) → docs.
4. `finish-branch` (FULL/LIGHT) — test-gated merge/PR + safe cleanup.

Periodically — monthly, or after a burst of work — run `curate`: a maintenance pass over
the skills, docs, recent changes and open predictions that produces a ranked backlog.
`develop` builds; `curate` is what keeps the fabric from silently accumulating debt.

Do **not** push or cut a release without an explicit go from the maintainer.

## Layout

```
hephaestus/
├── .claude-plugin/marketplace.json   # marketplace catalog (lists all plugins)
├── scripts/
│   ├── release.sh                    # per-plugin version bump + tag + GitHub release
│   ├── bump_version.py               # semver math (used by release.sh; unit-tested)
│   ├── validate_manifests.py         # marketplace + plugin manifest agreement (CI gate)
│   ├── check-public-safe.sh          # private-token guard (employer + third-party project)
│   ├── python_floor.py               # the declared floor, enforced (grammar + f-strings + stdlib)
│   ├── mtime_guard.py                # no shipped plugin code decides from st_mtime (AST, not grep)
│   ├── install_skills.py             # link skills into ~/.claude, ~/.codex, ~/.pi
│   └── checks/                       # the executable half of docs/INVARIANTS.md
│       └── _python.sh                # sourced: resolves a Python that actually runs
├── evals/                            # skill-eval harness (behavioral scenarios; see its README)
├── tests/                            # pytest suite (cms + eval core + loop-harness under test)
├── CLAUDE.md                         # this file
├── CONTRIBUTING.md
└── plugins/
    ├── crucible/
    │   ├── .claude-plugin/plugin.json
    │   ├── skills/{cms,spar-with-me,grill-me,start-branch,sync-branch,finish-branch,skill-craft,eval-first,flag-gate,loop-harness,act-for-real,repo-audit,refactor-audit}/
    │   ├── scripts/                 # detect_profile · evidence_gate · coverage_delta · invariants_run · new_skill · skill_lint (+ hook) · predictions
    │   ├── commands/{develop,curate}.md
    │   └── agents/qa-gatekeeper.md
    ├── forge-unity/             # Unity evidence + adapter contract (engine-specific, operator-free)
    │   ├── skills/{unity-bridge,unity-asset-integrity}/
    │   ├── scripts/{adapter.py,asset_integrity.py}
    │   └── commands/forge-init.md
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
