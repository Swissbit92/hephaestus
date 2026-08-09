# crucible

Generic, vendor-neutral **craft tools** for AI-assisted development — the flagship plugin of the
[hephaestus](../../README.md) marketplace. crucible makes day-to-day work with Claude Code
*disciplined* rather than chaotic: a structured workflow with real gates, a safe branch lifecycle,
documentation hygiene, change-gating that won't let quality regress, a bounded read-only
agent-loop harness, and a research-backed sparring partner for the thinking that happens before
any of it. Everything is pure-stdlib Python and plain markdown — no external dependencies,
nothing domain-specific, so it drops cleanly into any repo.

## Install

```
/plugin marketplace add Swissbit92/hephaestus
/plugin install crucible@hephaestus
```

Tools are namespaced under the plugin (`/crucible:<name>`). Skills load lazily — their full
instructions enter context only when invoked.

## What's in the box

| Tool | Type | What it does |
|------|------|--------------|
| **cms** | skill + hook | Context Management System — standardizes docs across repos for AI-agent token efficiency: frontmatter linting, ADR scaffolding, drift detection, staleness-based archival. A `PreToolUse` hook enforces frontmatter on `docs/*.md` edits. Plus the generated human view — `render` emits a self-contained HTML page for **any** document (its title taken from the document, not the caller) with layout-checked `archview` / `archflow` / `archplot` diagrams, and `site.py` builds a **multi-repo site** from the markdown already next to the code: a `site.toml` lists repositories and nothing else, *a page exists if its sources exist*, and the search index ships inline so every page still opens from a `file://` URL. |
| **spar-with-me** | skill | Sparring partner for the stage *before* a decision — when you have an instinct, not yet a thesis. Mandatory **internal *and* web** research before any opinion (neither substitutes for the other), clarifying questions only where a different answer would change the advice, and a take that moves on new evidence but never on restated preference. **Read-only**: research fans out to `Explore`/`Plan` agents that carry no write tools *by construction*, and nothing lands on disk until you ask — enforced for the fan-out, and measured for the main thread by a `pass^k` eval that fails on a single write. Hands off to `grill-me` once the idea hardens. |
| **grill-me** | skill | Adversarial stress-test of a decision you've already reached, before you commit to it (assumption audit, pre-mortem, outside view, falsifiable tripwires). Requires a position to attack — while one is still forming, that's `spar-with-me`. |
| **develop** | command | The structured workflow — classify → research → architect → isolate → implement → QA → docs → completion → integrate, with gates between phases. |
| **start-branch** | skill | Isolate work before implementing — detects the repo's integration target (never hardcoded), picks a plain branch vs. git worktree, names it Conventional-Branch style, records a clean test baseline. (`develop` ISOLATE phase.) |
| **finish-branch** | skill | Close out a branch/worktree safely — gates on tests (no green, no merge), offers merge / PR / keep / discard, PR-by-default for deploy branches, cleans up without losing unmerged work. (`develop` INTEGRATE phase.) |
| **qa-gatekeeper** | agent | Skeptical QA gate — verifies stated changes, hunts bugs/orphaned code, runs tests against a **live-derived** baseline (no stale-count false alarms), returns PASS / CONDITIONAL PASS / REJECT. (`develop` Phase 4.) |
| **eval-first** | skill | Freeze a baseline, then gate every change on **match-or-beat-or-revert**: deterministic-first checks → swap-augmented blind A/B judge (self-grading guard) → verdict. Generic stdlib scripts; domain scorers plug in via injected `judge_fn`/`embed_fn`. |
| **flag-gate** | skill | Default-OFF feature-flag rollout with instant revert — ship behind a flag, keep the legacy path byte-identical, flip only on an eval-first gate, revert by flipping off, retire after a soak. Pairs with `eval-first`. |
| **author-skill** | skill | Guide + scaffolder for writing a high-quality skill/plugin — the authoring patterns (with real exemplars) plus a pre-structured `SKILL.md` via `scripts/new_skill.py`. |
| **loop-harness** | skill | Run a bounded, single-threaded, **read-only** agent loop safely. Detailed below. |
| **act-for-real** | skill | The discipline for the opposite case: an **irreversible** action on a **live system you often don't own** (money movement, credential rotation, one-way migration, registrar/DNS, real mail). Classify reversibility → bind authority to the *exact* action → never fabricate a real-world identifier → **verify from a fresh read, not from the call** → record an `ACTION RECORD`, or say `UNVERIFIED`. Fires rarely by design. Counterpart to `loop-harness` (refuses prod) and `flag-gate` (revert by flipping). |
| **repo-audit** | skill + script | Recurring, repeatable **whole-repo health audit** — a deterministic pure-stdlib metrics anchor (`repo_metrics.py`: God-file density, tracked-artifact hygiene, gitignore gaps, flag-branching) plus four *frozen*, read-only, parallel analysis lenses (dead-code / structure / clean-code / config-hygiene), synthesized into a dated `docs/audits/` report you **trend over time**. Delegates docs to `cms`; the anchor score is reproducible so "72→68 since last quarter" means something. Not a diff review — that's `/code-review`. |

## The development loop, end to end

`develop` is the spine most of the other tools hang off:

```
/crucible:develop <task>
```

It classifies the task (FULL / LIGHT / TRIVIAL), then walks the matching phases — researching and
planning for risky work, isolating on a branch via `start-branch`, implementing in small
milestones with a `qa-gatekeeper` pass after each, updating docs via `cms`, and integrating via
`finish-branch`. Each gate is a real stop: no plan approval, no implementation; no green tests, no
merge. `eval-first` / `flag-gate` slot in when a change is LLM-backed or behavior-altering and you
want a measurable ruler before it ships.

## loop-harness — bounded, read-only agent loops

`loop-harness` is the primitive for running a long-running agent loop *bounded, single-threaded,
and safe* instead of unbounded and dangerous — the basis for a read-only **CI Sweeper** (watch
tests → triage → draft fixes in a worktree → surface a needs-me report; never merge, push, or
touch production). It is single-threaded by design, not a team of persona sub-agents — an
evidence-backed choice (see [`docs/research/loop-engineering-2025`](../../docs/research/loop-engineering-2025.md)).

Pure-stdlib scripts under `skills/loop-harness/scripts/`:

| Script | Role |
|--------|------|
| `loop_budget.py` | Hard **turn ceiling** (deterministic) + optional token/cost budget + per-run cost log. `arm` / `charge` / `status` / `disarm`. `charge` exits `3` when over budget. |
| `loop_ledger.py` | The loop's memory — a `LOOP-STATE.md` ledger (note-taking against context rot) with structural compaction. `init` / `append` / `compact`. |
| `loop_logscan.py` | Test-log summarizer (counts + failing node IDs); **refuses to report `ok` from output it can't parse**, so a sweep never claims green from unparsed logs. |
| `loop_hook.py` | A `PreToolUse` safety hook, **inert unless a loop is armed**; while armed it blocks `git push` / `merge` / `rebase` / `reset --hard` / `branch -d\|-D` / `worktree remove` and any write outside the worktree (tokenizer-based — resists `git -C` / `-c` / env-prefix bypass). |
| `loop_sweep.py` | One command for a read-only diagnostic sweep. |

### One-command read-only sweep

```
python3 skills/loop-harness/scripts/loop_sweep.py --test-cmd "pytest" [--worktree DIR] [--report needs-me.md]
```

Runs the project's test command, summarizes it, records findings to the ledger, and emits a
needs-me report. Exit **0 = green, 1 = red, 2 = couldn't parse a summary** — so cron or CI can act
on it. It is **read-only**: it never drafts a fix, commits, or merges. Drafting the fix is the
agent's triage step, run as a deliberate follow-up on what the sweep surfaces.

> Heads-up: `loop_logscan` needs the runner's pass/fail **summary** line. Use the project's normal
> test command — don't stack an extra `-q` on a repo whose pytest `addopts` already sets `-q`
> (it becomes `-qq` and suppresses the summary).

### Manual loop (when you want per-turn control)

```
loop_budget.py  arm   --goal "fix CI" --max-turns 20 --worktree "$WT"   # arms the safety hook
loop_ledger.py  init  --goal "fix CI" --run-id "$RID" --out "$WT/LOOP-STATE.md"
#   each turn: charge → work inside $WT → append to the ledger → check budget → stop when dry/exhausted
loop_budget.py  disarm --status converged                              # syncs the ledger, logs cost, disarms
```

## Conventions

- **Vendor-neutral & self-contained** — pure stdlib, no pip installs, no domain references.
- **Tested** — the cms scripts, the eval-harness core, and the loop-harness scripts are covered by
  the repo's `pytest` suite; run `pytest -q` from the repo root.
- Versioned independently; releases bump `version` in `.claude-plugin/plugin.json`.

See the [root README](../../README.md) for the full marketplace and the other plugins.
