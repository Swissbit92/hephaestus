---
name: cms
description: Context Management System — standardizes documentation structure across repos for AI-agent token optimization. Invoke for ANY .md file creation/edit (README, CLAUDE.md, CHANGELOG, ARCHITECTURE, ROADMAP, LESSONS_LEARNED, ADRs), new-repo scaffolding, doc health audits, cross-repo drift detection, and staleness-based archival. Enforces proximity-hierarchy context (root canonical → per-repo plain links), frontmatter-driven staleness tracking, and tiered Error/Warning linting. Use when the user asks to update docs, create a new repo, check doc health, run a drift report, create an ADR, or migrate bloated docs.
---

# CMS — Context Management System

Standardizes documentation across one or many repos so AI agents load the least context for the most signal. Enforces:

- **Per-repo skeleton**: README + CLAUDE.md + CHANGELOG + SECURITY.md + `docs/{ARCHITECTURE,ROADMAP,LESSONS_LEARNED,THREAT_LEVEL,INVARIANTS,decisions/,archive/YYYY-MM/}.md`
- **Standing constraints** live in `docs/INVARIANTS.md` — rules binding *all* work in the repo, as opposed to a spec, which describes one change and stops mattering once it ships. Filing the first inside the second is why standing constraints get lost. Scaffolded but **not required** (a repo may legitimately have none), **frontmatter-exempt** (a review date on a rule manufactures the rot it exists to prevent — retirement is a decision, not a timeout), and never auto-archived. `check` **warns, never errors**, on an active entry with no `Check:`; erroring would teach people to stop writing constraints down. Pipeline + worked examples: [references/invariants.md](references/invariants.md).
- **Root canonical**: shared facts live ONCE at `<root>/docs/shared/`. Repos reference them via **plain markdown links** (never `@path`).
- **Frontmatter** (required fields; canonical source is `scripts/common.py:FRONTMATTER_REQUIRED`): `title, status, created, last_reviewed_on, review_in, applies_to`. Optional controlled-vocabulary fields, validated only when present: `status` ∈ {active, completed, deprecated, Proposed, Accepted, Deprecated, Superseded}; `threat_level` ∈ {Low, Medium, High, Critical} (CVSS-aligned; used by `docs/THREAT_LEVEL.md`). Root files (README, CLAUDE, CHANGELOG, SECURITY) are frontmatter-exempt; `docs/*` always require it.
- **Archive rule**: `status: completed` OR a completion-artifact filename (`common.py:ARCHIVE_PATTERNS`) AND >60 days old AND not allowlisted. **Age is the git committer date, never mtime** — git does not restore mtimes, so on a clone every doc reads as 0 days old and the rule silently stops firing. Where nothing clone-stable can answer it emits nothing rather than guessing (`scripts/doc_age.py`).
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
| `/cms render [<path>]` | `render.py [<repo>]` | Render `docs/ARCHITECTURE.md` → `docs/ARCHITECTURE.html` (+ `.txt` for agents). `--check` exits 1 when stale; `--publish` prints the publish manifest line |
| `/cms triage` | `triage.py [--repo <p>] [--docs-dir <d>]` | Print the docs as a routing table — path, status, `ai_summary` — so a lookup reads one body instead of several |
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

The rules above were each adopted from a measured finding rather than a preference —
the ETH Zurich result on auto-generated context, the ~39% session-token drop from
converting `@path` to plain links, the UK Gov staleness pattern, tiered Error/Warning
enforcement, and creation-time scaffolding over retroactive audit. The citations and
the numbers: [references/design-rationale.md](references/design-rationale.md).

## Shared state

**Runtime state is never written inside the plugin.** Two reasons, and both bite:
it must survive a plugin update that overwrites the plugin dir, and it records one
entry per repo — so inside a generic (Tier A) plugin it becomes domain content,
which `tests/test_seam.py` rejects under ADR-001.

The split that follows from it: **versioned starters inside the plugin, accumulated
runtime data outside it.** `sync_facts.yaml` is shipped config; `size_history.json`
is runtime state. Anything you add obeys the same rule.

Resolution order, migration behaviour and the per-file table:
[references/shared-state.md](references/shared-state.md).

## Retrieval: summaries before bodies

The `@path`-vs-plain-link rule above controls what is loaded *unconditionally*. This
controls what is loaded *while looking for something* — the other half of the same bill,
and the one that grows with the corpus.

Searching by opening candidates costs the full text of everything you opened and were
wrong about. At ten documents that is fine; at fifty, finding one page costs most of a
context window. So documents may declare an optional **`ai_summary`** in frontmatter, and
`triage.py` prints them as a routing table: read the table, pick one document, open that
one.

Three rules make it work, and dropping any one of them turns the index back into a cost:

- **A summary says what the document is and when to open it — never what is in it.** The
  second kind is a second copy of the document, and it goes stale independently, which is
  worse than having no summary at all.
- **It is bounded** (`AI_SUMMARY_MAX_BYTES`, 1500 — about a short paragraph). It is re-read
  on every triage pass, so an unbounded summary is charged again and again for content
  you did not ask for. `check` raises a Warning past the cap.
- **It is optional, and documents without one are listed anyway**, marked and sorted last.
  An index that silently omitted them would route confidently around the part of the
  corpus it cannot see.

**Re-derive the summary whenever the body changes materially.** A summary describing the
previous version is worse than none: it is trusted, and it is wrong.

## Rendered architecture view

`docs/ARCHITECTURE.md` stays the single source; `docs/ARCHITECTURE.html` is
generated from it and **must never be hand-edited**. This deliberately does not
add a second architecture document — a second hand-maintained file would double
the staleness surface rather than solve it, so drift is made structurally
impossible instead of merely policed.

Diagrams and figures live in fenced blocks inside that one markdown file, the way
mermaid already does — ` ```archview ` (structure), ` ```archflow ` (a walk over an
existing view, so "what is here" and "what happens" cannot drift apart),
` ```archstat ` (a gauge row), ` ```archplot ` (a mechanism as a plot), and ` ```html `
as the escape hatch for the one visual a schema cannot anticipate. `site.py <root>`
builds a multi-repo site from the markdown already in the repos.

Four rules bind whenever you touch these; everything else is schema:

- **`check_arch.py` is the authority on layout, not the eye.** Layout engines do not
  fail loudly — they route a connector through a box and it looks plausible.
- **Staleness is gated on content hashes of the source and the renderer, never
  mtimes** — git does not preserve mtimes, so a fresh checkout would report a
  byte-identical page as stale. `check` raises it as a Warning, never an Error: a
  gate that blocks on a regenerable artifact is one people learn to bypass.
- **`check` warns when prose describes a sequence of 4+ steps and no `archflow`
  renders it.** That omission went unnoticed for weeks — the capability had shipped
  and the content had not, which nothing checking *whether the page builds* can see.
- **Generated plot data must declare `"schematic": true`** or the render refuses; a
  gauge row is where "STRUCTURE ONLY, NO RUNTIME STATE" usually dies.

Block schemas, the view catalogue, `site.toml`, state pills, `published_url`, `accent`
and the authoring rules: [references/architecture-views.md](references/architecture-views.md).

## Hook scope

The bundled PreToolUse hook (`scripts/hook.py`) gates `.md` writes/edits under `docs/`.
By default it scopes to the **current working directory**. Set `CMS_ROOTS` (an
OS-path-separated list of directories) to gate a fixed set of repos regardless of cwd.
README/CLAUDE.md/CHANGELOG and anything under `docs/archive/` are exempt.
