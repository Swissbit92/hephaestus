---
name: repo-audit
description: Recurring, repeatable repository health audit — a deterministic metrics anchor plus four frozen read-only analysis lenses (dead-code, structure, clean-code, config-hygiene), synthesized into a dated report you can trend over time. Use when the user wants a repo-health check, a tech-debt / bloat / dead-code audit, a "how healthy is this codebase" assessment, a structural review of a whole repo (not a diff), or wants to track code quality across time. Not for reviewing a single change — that's code review.
---

You run a **repeatable** health audit of an entire repository and write a dated report that the
*next* run can diff against. The value isn't one snapshot of findings — it's the **trend**: is
this repo's debt growing or shrinking since last quarter? That only works if every run measures
the same way, so this skill's core discipline is **freeze the ruler**: a deterministic metrics
script for the numbers, and four *verbatim-frozen* analysis lenses for the judgment.

## When this applies

A whole-repo health check, run from time to time (per major phase-boundary, or quarterly) — dead
code, bloat, God files, structural debt, config hygiene, doc rot. **Not** a code review: this is
wide-and-shallow across the committed tree, not deep on a diff. For a specific change, use
`/code-review`; for security of pending work, `/security-review`. This audit *complements* them.

## Why this isn't role-play (the VISION reconciliation)

hephaestus rejects the sequential role-play waterfall (PM → architect → dev → QA), because adding
sequential, shared-state roles *degrades* a single software task. This audit is the opposite shape
and does not trip that rule: the four lenses are **read-only, independent, and parallel** — they
analyse the *same static tree* from different angles and never hand state to one another. There is
no pipeline, no role negotiating with another role, no shared mutable work product. It is exactly
the "parallelism only for genuinely independent sub-tasks" the VISION endorses. The durable value
is **verification of what already exists**, not a team pretending to build something.

## The discipline

1. **The number is deterministic; the prose is judgment.** `repo_metrics.py` computes an
   `anchor_score` from hard facts — same commit, same score, every time. That is the figure you
   trend. The lenses' holistic "quality read" is coarse (±5 run-to-run); never trend on it alone.
2. **The lenses are frozen.** Feed `templates/lens_prompts.md` verbatim. Do not paraphrase or
   "improve" them between runs — a moved ruler makes the trend a lie. Change them only by bumping
   `LENS_VERSION` and saying so in the report.
3. **Read-only, always.** Every lens is an `Explore` agent. The audit never edits code. Its output
   is a report, not a patch. Acting on findings is separate, deliberate work (via `/crucible:develop`).
4. **Reuse, don't reimplement.** The docs dimension is `/crucible:cms check` — do not hand-roll doc
   analysis. Security leans on the same patterns as `/security-review`.
5. **The report is versioned; the raw dumps are not.** Only the synthesized report lands in
   `docs/audits/`. Raw per-lens agent output is an ephemeral artifact — gitignore it (the
   eval-first artifact-hygiene lesson: repeated runs must not accrete MBs of committed dumps).

## The workflow

1. **Scope.** Resolve the target repo (argument, else cwd). Confirm the repo name used in the
   report path.

2. **Anchor — deterministic metrics.** Run the metrics script and keep its JSON; it is ground
   truth for every lens:
   ```
   python3 {SKILL_DIR}/scripts/repo_metrics.py <REPO_ROOT>
   ```
   Tune with `--god-threshold N` or repeated `--flag-pattern RE` for the repo's stack. It reads
   **git-tracked files only** (what's committed, not local scratch), pure-stdlib, no installs.

3. **Lenses — four frozen, parallel, read-only agents.** Launch all four in one message (they are
   independent). Feed each the verbatim prompt from `templates/lens_prompts.md` with `{REPO_ROOT}`
   and `{METRICS_JSON}` substituted. Each returns a findings list (path, evidence, severity,
   confidence). They read the metrics as truth and never recompute it.

4. **Docs — delegate to cms.** Run `/crucible:cms check` on the repo for the documentation
   dimension (staleness, frontmatter, drift). Fold its summary into the report; don't duplicate it.

5. **Diff against last.** Read the most recent prior report in `<REPO_ROOT>/docs/audits/` (if any).
   Compute: anchor Δ, which findings **closed**, which are **new**, which are **still open/deferred**.
   On the first run, say so — this run becomes the baseline the next one diffs against.

6. **Synthesize.** Fill `templates/report_template.md`: score table (anchor + lens read, both with
   Δ), since-last-audit, the four lens reports, cms summary, the priority matrix (rank the top
   5–7 cleanups by impact-vs-effort), and a sequential cleanup plan. Keep the anchor's
   `score_breakdown` visible so the number is explainable.

7. **Write the report via cms.** Save to `<REPO_ROOT>/docs/audits/{YYYY-MM-DD}-{repo}.md`. It goes
   through the cms frontmatter hook (the template already carries valid frontmatter). Ensure
   `docs/audits/.raw/` is gitignored and drop the raw per-lens output there if you keep it.

8. **Report the headline** to the user: anchor score + Δ, primary bottleneck, and the top 3
   actions. Point them at `/crucible:develop` to act on any of it — the audit itself changes nothing.

## Cost & cadence

Four `Explore` agents plus a metrics pass is a real spend (~200–300k tokens per repo). This is a
*from-time-to-time* tool — a phase-boundary or quarterly check — not a per-commit hook. It can be
fired on a schedule (`/schedule`, `/loop`) if you want, but a health audit nobody reads on a fixed
day is just tokens; prefer deliberate manual runs.

## Anti-patterns

- **Improvising the lens prompts each run** — the trend is only real if the ruler is frozen. Use
  the templates verbatim; version them if they must change.
- **Trending the lens quality read instead of the anchor** — the LLM read wobbles; the anchor
  doesn't. Trend the anchor, let the read explain it.
- **Editing code from the audit** — it's read-only by design. Findings feed a *separate* develop
  cycle; an audit that also fixes things is no longer a repeatable measurement.
- **Committing the raw agent dumps** — only the synthesized report is versioned; raw output is
  gitignored, or repeated audits bloat the repo they're supposed to keep lean.
- **Reimplementing doc analysis** — call `/crucible:cms check`; don't grow a second, drifting copy.
- **Running it as a diff review** — wrong tool; whole-repo audit ≠ change review (`/code-review`).

Pairs with the rest of the forge: `cms` (docs dimension), `flag-gate` (the flag-debt the Janitor
lens surfaces), `develop` (the cycle that acts on findings). The audit measures; the others fix.
