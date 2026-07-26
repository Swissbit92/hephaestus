---
name: cms
description: Context Management System — standardizes documentation structure across repos for AI-agent token optimization. Invoke for ANY .md file creation/edit (README, CLAUDE.md, CHANGELOG, ARCHITECTURE, ROADMAP, LESSONS_LEARNED, ADRs), new-repo scaffolding, doc health audits, cross-repo drift detection, and staleness-based archival. Enforces proximity-hierarchy context (root canonical → per-repo plain links), frontmatter-driven staleness tracking, and tiered Error/Warning linting. Use when the user asks to update docs, create a new repo, check doc health, run a drift report, create an ADR, or migrate bloated docs.
---

# CMS — Context Management System

Standardizes documentation across one or many repos so AI agents load the least context for the most signal. Enforces:

- **Per-repo skeleton**: README + CLAUDE.md + CHANGELOG + SECURITY.md + `docs/{ARCHITECTURE,ROADMAP,LESSONS_LEARNED,THREAT_LEVEL,decisions/,archive/YYYY-MM/}.md`
- **Root canonical**: shared facts live ONCE at `<root>/docs/shared/`. Repos reference them via **plain markdown links** (never `@path`).
- **Frontmatter** (required fields; canonical source is `scripts/common.py:FRONTMATTER_REQUIRED`): `title, status, created, last_reviewed_on, review_in, applies_to`. Optional controlled-vocabulary fields, validated only when present: `status` ∈ {active, completed, deprecated, Proposed, Accepted, Deprecated, Superseded}; `threat_level` ∈ {Low, Medium, High, Critical} (CVSS-aligned; used by `docs/THREAT_LEVEL.md`). Root files (README, CLAUDE, CHANGELOG, SECURITY) are frontmatter-exempt; `docs/*` always require it.
- **Archive rule**: `status: completed` OR filename matches `*_MIGRATION.md|*_PLAN.md|*_COMPLETE.md|RUNBOOK_*|*_ASSESSMENT.md|*_REVIEW.md|PHASE*_*.md` AND >60 days old AND not in protected allowlist
- **CLAUDE.md discipline**: keep lean; front-load invariants; use plain links for reference content — not `@path`

## Commands

All commands are Python scripts (pure stdlib, Python 3.9+). The scripts live at
`${CLAUDE_PLUGIN_ROOT}/skills/cms/scripts/`. Run via:

```
python3 "${CLAUDE_PLUGIN_ROOT}/skills/cms/scripts/<name>.py" <args>
```

If `CLAUDE_PLUGIN_ROOT` is unset (e.g. running the scripts outside the plugin
runtime), substitute the absolute path to this skill's `scripts/` directory.

| Command | Script | Purpose |
|---------|--------|---------|
| `/cms init <path>` | `init.py <path>` | Scaffold standard skeleton into a new or underdocumented repo (idempotent) |
| `/cms check [<path>]` | `check.py [<path>]` | Lint against standard. Tiered Error/Warning. Exit non-zero on Error |
| `/cms check --mechanical <file>` | `check.py --mechanical <file>` | Fast frontmatter check. Used by PreToolUse hook |
| `/cms new-adr <title>` | `new_adr.py "<title>" [--path <dir>]` | Scaffold next NNN-title.md ADR with Nygard template |
| `/cms sync` | `sync.py [<root>]` | Cross-repo drift detector (regex allowlist of known-drift facts in `state/sync_facts.yaml`) |
| `/cms migrate <path>` | `migrate.py <path>` | Propose-and-approve structural migration (extract to docs/, archive stale) |
| `/cms render [<path>]` | `render.py [<repo>]` | Render `docs/ARCHITECTURE.md` → `docs/ARCHITECTURE.html`, a human-readable view. `--check` exits 1 when stale |
| — | `check_arch.py <html>` | Structural check on a rendered page's diagrams (overlaps, connectors through boxes, out-of-bounds) |

Invoke this skill with `/crucible:cms`. The `/cms <subcommand>` forms above are
the conceptual interface — map them to the scripts as shown.

## Invocation rules

**BLOCKING REQUIREMENT:** Before writing or editing ANY `.md` file under `docs/` or any `CLAUDE.md`:

1. Read the file (if exists) to understand current state.
2. Run `check.py <target-file>` to see current violations.
3. Apply changes (content comes from you/the user — skill never paraphrases prose).
4. Re-run `check.py` to verify zero Errors.

**For new repos:** Run `init.py <repo-path>` first. Do NOT manually create README/CLAUDE.md in isolation.

**For new ADRs:** Always use `new_adr.py` — it picks the next number and applies the Nygard template.

**For MIGRATE:** Always propose-and-approve. Never auto-apply CLAUDE.md content changes. Mechanical moves (file → archive/YYYY-MM/) may auto-apply since they're reversible via git.

## CLAUDE.md content rules

### What belongs inline (auto-loaded every session — earn every line)

- Hard invariants Claude must not violate (decommission rules, public APIs, single-source constraints)
- Non-obvious commands Claude can't guess (custom test markers, build flags, generators)
- Safety-critical conventions that apply to all work in this repo
- Session management pointers (`/clear`, `/compact`, and your project's workflow/doc commands)

### What belongs in a linked doc (fetched only when needed)

- Full CLI reference / all commands → `docs/DEVELOPMENT.md`
- Architecture, pipeline design, module maps → `docs/ARCHITECTURE.md`
- Data schema details, collection/table listings → `docs/ARCHITECTURE.md` or `docs/shared/`
- Scheduled-job / cron tables → `docs/shared/`
- Conventions reference (test patterns, code style) → `docs/DEVELOPMENT.md`
- Container/infra commands → `docs/DEVELOPMENT.md`

### Never use `@path` in CLAUDE.md

`@path/to/file` is **eagerly loaded** at session start — it adds tokens unconditionally regardless of whether the content is needed for the task at hand. Plain markdown `[links](path)` are fetched **on demand**, only when Claude explicitly reads them. This is the real lazy-loading mechanism.

**Rule:** use plain `[label](path)` links everywhere in CLAUDE.md. Reserve `@path` for nothing — there are no cases where a CLAUDE.md reference genuinely needs to be auto-loaded (the invariants themselves stay inline as prose; they don't need file imports).

## Skill principles (why, not just what)

- **ETH Zurich finding:** auto-generated CLAUDE.md content is ~20% more expensive and 0.5-2% worse on task success than hand-curated. This skill **moves structure, does not paraphrase prose**.
- **Plain links are lazy, @path is eager:** discovered during a live migration when `@path` was incorrectly introduced as a "lazy-loading" mechanism. It is not. In the ecosystem this skill was built for, converting all `@path` to plain links cut session token load by ~39% (836 → 507 total CLAUDE.md lines across 6 repos).
- **Codex 32 KiB cap + proximity hierarchy:** Claude loads the nearest CLAUDE.md first. Keep root lean, per-repo specialised, avoid duplication.
- **UK Gov staleness pattern:** `last_reviewed_on + review_in → review_by` exposes doc expiry machine-readably.
- **GitLab/Datadog tiered CI:** Error blocks, Warning informs — keeps enforcement trustworthy at scale.
- **Nx/Kubernetes creation-time enforcement:** scaffold correctly at `/cms init` rather than audit retroactively.
- **Skill content is lazy-loaded correctly:** skill descriptions are small and load at session start; the full skill body only loads on invocation. The right pattern for large reference content needed only for specific tasks.

## Shared state

**Runtime state is never written inside the plugin.** Two reasons, and both bite:
it must survive a plugin update that overwrites the plugin dir, and it records one
entry per repo — so inside a generic (Tier A) plugin it becomes domain content,
which `tests/test_seam.py` rejects under ADR-001.

Resolution order:

1. `CMS_STATE_DIR` env var, if set
2. `${CLAUDE_PLUGIN_DATA}/cms-state` when running as a plugin
3. `~/.claude/cms-state` — the default in ordinary use, since neither env var is
   normally set

State written by older versions is migrated out of `<skill>/state/` on first run
and the legacy copy removed. The migration is non-destructive: an existing file at
the new location always wins.

Files:

- `size_history.json` — per-repo CLAUDE.md line-count history (for the "grew >20%" warning). **Runtime state** — lives in the resolved state dir above.
- `sync_facts.yaml` — regex allowlist of known-drift facts (ships empty; grows as you find drift). **Shipped config** — versioned with the plugin at `<skill>/state/`, which is why `sync`'s default `--facts` path points there. It must stay free of ecosystem-specific tokens.

Anything you add here follows the same split: versioned starters in the plugin,
accumulated runtime data outside it.

## Rendered architecture view

`docs/ARCHITECTURE.md` stays the single source; `docs/ARCHITECTURE.html` is
generated from it and **must never be hand-edited**. This deliberately does not
add a second architecture document — a second hand-maintained file would double
the staleness surface rather than solve it, so drift is made structurally
impossible instead of merely policed.

- Diagrams live in fenced ` ```archview ` blocks inside the markdown, the way
  mermaid already does. One file to edit, one linter to satisfy.
- Repo-specific visuals go in a fenced ` ```html ` block and pass through
  untouched — "the one thing this repo does" differs everywhere and cannot be
  schema'd, so the format offers a socket rather than a type.
- The palette accent comes from frontmatter (`accent: "#RRGGBB"`), so visual
  identity belongs to the repo, not to this skill.
- Staleness is gated on **content hashes of both the source and the renderer**,
  never mtimes — git does not preserve mtimes, so a checkout reports a
  byte-identical page as stale. `check` surfaces it as a Warning, never an Error:
  a gate that blocks on a regenerable artifact is one people learn to bypass.
- **`check_arch.py` is the authority on layout, not the eye.** Layout engines do
  not fail loudly; they emit a connector through a box and it looks plausible.

Full schema, view catalogue and authoring rules: [references/architecture-views.md](references/architecture-views.md).

## Hook scope

The bundled PreToolUse hook (`scripts/hook.py`) gates `.md` writes/edits under `docs/`.
By default it scopes to the **current working directory**. Set `CMS_ROOTS` (an
OS-path-separated list of directories) to gate a fixed set of repos regardless of cwd.
README/CLAUDE.md/CHANGELOG and anything under `docs/archive/` are exempt.
