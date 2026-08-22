---
title: "Repo Audit — hephaestus — 2026-08-22"
status: active
created: 2026-08-22
last_reviewed_on: 2026-08-22
review_in: 3 months
applies_to: hephaestus
ai_summary: "First repo-audit of hephaestus, at ba9cdb0 (crucible 1.3.0). Anchor 50/100 — a BASELINE, not a grade; the God-file penalty that supplies 80% of the deduction rests on a premise the empirical literature does not settle. The urgent findings are not structural: the public-safety guard publishes its own ~35-token denylist and exempts itself from its own scan, two docs disclose a live-capital system's venue plus key-location plus datastore, and .env is not gitignored because this repo's own shipped metrics tool substring-matches it against .venv. The dominant structural fact is that render.py plus its tests are 15.5% of all source for a feature this repo never runs on itself. Read before acting on any anchor score, and before the next audit."
---

# Repo Health Audit — hephaestus

**Date:** 2026-08-22 · **Commit:** `ba9cdb0` · **Lens version:** 1 · **Metrics:** 203 files, 22,871 source lines

## 1. Score

| | This audit | Last audit (—) | Δ |
|---|---|---|---|
| **Anchor score** (deterministic, trend-grade) | **50**/100 | — | — (baseline) |
| Lens quality read (coarse, directional) | ~62/100 | — | — (baseline) |

**Anchor breakdown:** `start 100 → god_file −40 → gitignore_gap −10 → artifact 0 · large_file 0 · dead_candidate 0 → final 50`

### Read this before reading the number

**50/100 does not mean "half rotten", and this report will not let that reading stand.**

Two things about the anchor need saying at the top, because a scary number travels further
than its caveats:

1. **80% of the deduction is the God-file penalty, and that premise is not settled.**
   The empirical literature finds
   [no statistical evidence that files past a size threshold are more defect-prone](https://posl.ait.kyushu-u.ac.jp/~kamei/publications/Yamashita_QRS2016.pdf),
   and the God Class evidence is genuinely mixed — one large investigation found smelly
   classes were changed *less* often and carried *fewer* defects than clean ones
   ([Palomba et al., EMSE 2018](https://link.springer.com/article/10.1007/s10664-017-9535-z)).
   Composite maintainability scores are criticised for precisely our shape: arbitrary
   weights, overweighted LOC, cancellation between terms
   ([Teamscale](https://teamscale.com/blog/en/news/blog/maintainability-index),
   [Sourcery](https://www.sourcery.ai/blog/maintainability-index)).

2. **The defensible use is the one this skill already mandates: trend it, don't grade it.**
   The literature's own recommendation is to "measure relative maintainability *within*
   our project rather than as an absolute metric". This run exists to be the baseline the
   next one diffs against. Treat any single-run absolute as noise.

**Four of the eight God files are test files** (`test_cms_render.py` 1410,
`test_cms.py` 1025, `test_loop_harness.py` 528, plus `evals/fixtures.py` 963). Test length
tracks coverage, not complexity; the metric cannot tell them apart, which inflates the
penalty further. Tests are 8,773 lines against 11,069 in `plugins/` — a healthy ratio.

**And 3 of the 5 gitignore gaps are unreachable here** — `.coverage`/`htmlcov` have no
coverage tooling behind them, `*.log` has no producer. Call the 10-point penalty ~2 points
real. But see **S3**: the gap that *does* matter was not reported at all.

**Primary bottleneck:** not the score. **The urgent findings are security and wiring, not
structure.** The dominant *structural* fact is that `render.py` + its tests are 15.5% of
all source for a feature this repo never runs on itself.

**Where the recommendation survives anyway:** splitting `render.py` is justified — just not
by the line count. Refactored components show fewer inter-module dependencies and fewer
post-release defects ([Kim et al., TSE 2014](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/kim-tse-2014.pdf)),
and locally there are 576 lines of CSS/JS sealed inside a Python string where no linter can
reach them, plus four independent readers of one undocumented DSL. **The line count is the
smoke, not the fire.**

## 2. Since last audit

- **Closed:** — · **New:** — · **Still open:** —

*First audit for this repo. This section becomes the spine of every future run.*

## 3. Security — surfaced ahead of the lens reports

These were found by the DevOps lens and **independently re-verified in the main loop**
(the repo's own provenance rule: a claim from another agent is an input, not a fact).
Values are deliberately not reproduced here.

**S1 — The secret-guard publishes its own denylist, on a public repo, and exempts itself.**
`scripts/check-public-safe.sh` holds **~35 tokens in plaintext** — the list of names it
exists to keep out — in a repo GitHub reports as `PUBLIC`. Line 40 skips the guard itself,
so it can never flag its own contents. A denylist is the one artifact that must not ship
with the thing it protects: a reader who knew none of those names now has all of them,
curated and labelled as sensitive. ADR-002 assessed the history hits as "benign" — true for
a private repo, inverted for a public one. The header still reads "This repo is PRIVATE",
which ADR-002 item 3 explicitly required be made visibility-neutral.
**Severity: HIGH · Verified.**
*Fix:* move `PATTERN` to an untracked, gitignored file; exit **2** when it is absent so a
missing file never reads as a pass; delete the self-exemption; fix the header.

**S2 — Two docs disclose the topology of a live-capital system.**
`SECURITY.md` and `docs/THREAT_LEVEL.md` between them name a **specific trading venue**
(6 mentions), **where the API keys are held** (2), and **which datastore holds the trading
data** (2) — attached to a named GitHub identity with a real commit email. ADR-002 accepted
project *mentions* because they "name no credential, address, strategy parameter or capital
figure". That reasoning does not extend here: venue + key location + datastore is a
reconnaissance profile. **The guard catches none of it** — all three terms verified absent
from `PATTERN`. That is the second-order lesson: a denylist only stops what someone already
thought of. **Severity: HIGH · Verified.**

**S3 — `.env` is not gitignored, and this repo's own shipped tool hides that.**
`repo_metrics.py:276` normalises `.env` to the needle `env`, then substring-matches against
`.gitignore`, where `.venv` contains `env`. It therefore reports `.env` as covered. It is
not — there is no literal `.env` entry. On a public repo whose CI docs tell contributors to
hold an `ANTHROPIC_API_KEY`, a dropped `.env` is one `git add -A` from publication. **Any
consumer repo with a `.venv` line gets the same silent pass** — this is a defect in
`repo-audit` as shipped, not just here. **Severity: MEDIUM-HIGH · Verified.**

**S4 — Branch protection gates one of three hermetic jobs, and the release path bypasses
even that.** `required_status_checks.contexts` is `["checks"]` only; `enforce_admins:
false`; no review requirement. So `cross-platform` (macOS + Windows) and `python-floor`
(3.9–3.13) can be red and `main` still accepts. The CI comments go to real lengths
explaining how matrixing would rename the required check and "detach the rule without
anything appearing to break" — it is detached now, by omission rather than renaming.
`release.sh` pushes directly to `main` as the admin who bypasses, and publishes the tag and
GitHub release *before* CI starts. **Severity: HIGH · Verified.**

## 4. Lens reports

### 🧹 Janitor — dead code & bloat

Empty `dead_module_candidates` is **correct at file granularity** — every tracked file has
a live reference. The dead weight is sub-file.

- **`render.py` is not dogfooded.** *Verified:* `grep '```arch'` across **all** of `docs/`
  returns **0**, and no `docs/ARCHITECTURE.html` is committed. `check_architecture_page` is
  silent by design when no rendered page exists, so nothing ever notices. 3,546 lines
  (renderer + tests) = **15.5% of all source** for a feature the repo never runs on itself.
- **`evals/` has never frozen a baseline.** *Verified:* `evals/baselines/` holds only
  `.gitkeep`. ~1,900 source lines plus 43 KB of docs, and the `live-eval` CI job only fires
  on dispatch/schedule and needs a key. The largest speculative investment in the repo —
  and one locally-frozen baseline would make it load-bearing.
- **`CHANGELOG.md` is 87,485 bytes in 120 lines — exactly 5.0% of all repo bytes**
  (*verified*), ~729 bytes/line against README's 72. `check_claude_md_size_trend` measures
  **lines** and only inspects `CLAUDE.md`, so it is structurally blind to this shape.
- **Dead functions:** `ab_harness.py:121–147` (`run_cli`, `save_ratings` — no `__main__`, no
  caller, undocumented in SKILL.md); `fixtures.py` `spar_underspecified` + `_SPAR_UNDERSPEC_ADR`
  (~120 lines, referenced by zero scenarios and zero tests).
- **`invariants_run.py` is not wired into CI** — and all four of its checks are already
  covered by CI through another path, so the shell layer is a parallel mechanism over
  ground already held. Wire it in or drop the shims.
- **No feature-flag debt.** All 41 hits are configuration, read once, none gating a
  retirable path. Note `repo_metrics.py` contributes 3 hits *by containing its own
  detection regexes* — `flag_hit_total` should not be trended without excluding the detector.

### 🏛️ Architect — structure & modularity

**Verdict: in-between — a genuinely layered, seam-enforced marketplace with one
big-ball-of-mud leaf.** The outer layout communicates the architecture and is mechanically
enforced (`test_seam.py`). The principle stops at `skills/cms/scripts/`: 13 flat modules,
~5,000 lines, no internal layering.

- **`render.py` = eight responsibilities**, with named seams: layout (L380–642, already
  dependency-free), theme assets (L1274–1891, of which **576 lines are CSS/JS in a Python
  string**), four figure renderers, a plot *simulator*, markdown, provenance, CLI.
- **⚠️ Load-bearing trap, verified:** `_gen_hash()` (L1899) hashes `Path(__file__)` **only**.
  Split the file naively and the staleness gate silently narrows to whichever fragment
  `build` lands in — a CSS edit would stop invalidating pages. The hash must be redefined
  over the whole package **in the same commit** as the split.
- **The `archview` DSL has four readers and no source of truth.** `check_arch.py` validates
  by regex-scraping the renderer's own emitted SVG, so it can only catch defects that
  survive into pixel coordinates. An unknown `kind` silently falls back in four places.
- **Flat namespace forces workarounds:** `site.py` shadows stdlib `site` (tests load it by
  path); `loop_common.py`'s prefix is a documented collision patch; `conftest.py` needs
  **nine** `sys.path.insert` calls.
- **Tests run two competing schemes** (per-module vs per-area) and the two oversized files
  are exactly the per-area ones. Splitting `render.py` yields the test split for free.

### 🔬 Clean Code — refactoring

**The debt is not sloppiness — it is forking.** The same logic exists 2–6 times because
there was no seam to share it, and the forks have drifted into wrong behaviour.

- **The hook and the linter disagree — corrected from the lens's account.** The lens claimed
  the hook "waves through" the unterminated-fence fault. *Verified: it does not.* It
  **blocks, with the wrong diagnosis** — an unterminated fence and a file with no
  frontmatter produce the **identical** message, "Missing frontmatter in doc.md…". So the
  author is told to add frontmatter that is already present and only needs a closing fence.
  Real finding, lower severity than stated: **today's `check.py` fix was half-applied**;
  `hook.py` imports `frontmatter_is_unterminated` zero times and bounds `ai_summary` zero times.
- **`_utf8_stdio` is copy-pasted into 35 files** (*verified; lens said 31*) ≈ 500 lines.
  `loop_common.py`'s copy has already diverged — it omits `errors="replace"`.
- **`archplot` is missing from the fence allowlist** at `check.py:372` (*verified* — 4 of 5
  listed), so `archplot` bodies are fed to the arrow-cascade heuristic.
- **Worst functions:** `render_markdown` (172L, nesting **7**, hand-rolled index-cursor
  parser where every branch must prove it advances — and one already failed to, per its own
  guard comment); `build_text` (99L, nesting 7, a second copy of the same scanner).
- **Authored error messages that never reach the user:** `render.py` defines three exception
  types with actionable text; `main()` catches exactly one. The other two print as
  tracebacks. Worse, the *same* malformed input is fatal in `render_markdown` and silently
  dropped in `build_text`, and `main()` runs both.
- **Import-time side effects:** the MCP server materialises a DB file and opens a connection
  at import; `common.py` runs a `glob`+`unlink` migration at import — on every hook fire.
- **A read-only check that writes:** `check_claude_md_size_trend` calls `save_state` inside
  `run_repo_check`, so `/cms check` is not idempotent.
- **3.9-safe wins:** `removeprefix` (~8 sites), `lru_cache` on `_gen_hash` (currently
  re-SHA-256s 2,136 lines on every call, per page), `graphlib.TopologicalSorter` for the
  hand-rolled layerer, `dict |` merge.

### ⚙️ DevOps — config & hygiene

Security items are **S1–S4** above. Remaining:

- **`SECURITY.md` scopes a plugin that does not exist** (*verified*: no
  `plugins/kucoin-safety-gate`; ROADMAP records it parked 2026-06-28). `THREAT_LEVEL.md`'s
  headline `Medium` rating and two of its rows cite that nonexistent control.
- **`release.sh` runs none of the gates ADR-002 promoted to release gates** — no `pytest`,
  no `check-public-safe.sh`, no `validate_manifests.py`.
- **Zero static analysis** on 22.5k lines: no ruff/mypy/pre-commit config anywhere, while
  `evidence-profiles.md` describes running them and `.crucible/evidence.json` quietly
  encodes their absence.
- **Lockfile asymmetry:** `sqlite-readonly` is locked; `mcp-starter` — the explicit copy-me
  template — is not, so the unlocked variant propagates downstream.
- **Neither MCP server is ever imported in CI** (only `pip install pytest`), so both
  entrypoints and the FastMCP wrapper ship unexercised.
- **`--staged` pre-commit mode is advertised and never wired**; `.git/hooks/` holds only samples.
- **Repo root is clean** — eight canonical files, thorough `.gitattributes`. No finding.

### 📄 Docs — cms health

`cms check`: **0 errors, 0 warnings**, 1 info. `triage`: **12 summarised / 0 without** —
full routing coverage. `sync`: 0 facts, exit 0 (honest empty, post-1.2.0). `skill_lint
--strict`: **0 error / 0 warn** across 17 skills. Invariants **4/4**.

The documentation *standard* is in excellent shape. The doc **content** problems are S2 and
S5 — and neither is something `cms check` can see, because both are semantic.

## 5. Refactor priority matrix

| # | Task / File | Issue | Effort | Impact | Actionable fix |
|---|---|---|---|---|---|
| 1 | `scripts/check-public-safe.sh` | **S1** denylist published + self-exempt, on a public repo | S | **Critical** | Move `PATTERN` to untracked file; exit 2 if absent; drop self-exemption; fix "PRIVATE" header |
| 2 | `SECURITY.md`, `docs/THREAT_LEVEL.md` | **S2** venue + key location + datastore disclosed | S | **Critical** | Generalise to "a live trading venue", "credentials held outside the repo" |
| 3 | `.gitignore` + `repo_metrics.py:276` | **S3** `.env` unignored; substring bug hides it | XS | **High** | Add `.env`/`.env.*`; match whole normalised entries, not substrings |
| 4 | GitHub branch protection | **S4** 2 of 3 jobs not required; admins bypass; no reviews | XS | **High** | Add `cross-platform`+`python-floor` contexts; `enforce_admins: true` |
| 5 | `scripts/release.sh` | Publishes before CI; runs no gates; leaves `dev` behind | S | **High** | Run suite + public-safe + manifests pre-push; gate release on CI; ff `dev` |
| 6 | `hook.py` ↔ `check.py` | Hook misdiagnoses unterminated fence; validator forked | M | High | Extract one `validate_frontmatter`; one `requires_frontmatter` (4 spellings today) |
| 7 | `render.py` → `render/` package | 8 responsibilities; 576 lines unlintable CSS/JS; 4 DSL readers | **L** | High | Split on the named seams — **redefine `_gen_hash()` over the package in the same commit** |
| 8 | `docs/ARCHITECTURE.md` | Renderer never dogfooded (0 arch blocks repo-wide) | S | Medium | Add one `archview` block, or accept the 3,546 lines are unvalidated |
| 9 | `evals/baselines/` | No baseline ever frozen; ~1,900 lines speculative | S | Medium | Freeze one locally (`bare=False`, no key needed) |
| 10 | `CHANGELOG.md` | 5.0% of repo bytes; size check is blind to it | S | Low-Med | Archive pre-1.0 entries; make the trend check measure bytes |

## 5b. Acted on, same day (waves A · C · D · E · G)

| Item | Status | Evidence |
|---|---|---|
| #3 `.env` + substring bug | ✅ fixed | `.env`/`.env.*` ignored; `_covered_by` matches whole entries. Was hidden by `.venv` |
| #4 Branch protection | ✅ applied | 7 contexts required, `enforce_admins: true`, `strict: true` |
| #5 `release.sh` gates | ✅ fixed | pytest + public-safe + manifests at line 62, push at 157; `dev` fast-forwarded after |
| #6 Shared frontmatter validator | ✅ fixed | `common.validate_frontmatter` + `requires_frontmatter`; 4 predicate spellings → 1 |
| #8 Renderer dogfooded | ✅ done | 1 `archview` block in `ARCHITECTURE.md`, renders + passes `check_arch` |
| #9 Eval baseline | ⚠️ partial | 1 of 32 scenarios frozen — exercises the path, not yet a ruler |
| S1, S2 (disclosure) | ⏸ deferred | Wave B — the maintainer's judgement, not a code question |
| #7 `render.py` split | ⏸ deferred | Wave F — its own session |

**Two things the acting found that the audit did not.**

**The renderer's structural checker earned its place on first use.** `check_arch.py`
*rejected* the first `archview` block written for this repo — a real C4 violation, a node
straddling the group boundary — caused by two backward edges, since layering is
longest-path over forward edges only. Reordering fixed it. The audit called those 3,546
lines "unvalidated against a real document"; the first real document found a genuine
defect in the diagram, which is the checker working exactly as its docstring claims. The
same block then pushed `ARCHITECTURE.md` past the acronym threshold, so `cms check`
demanded a Glossary — a second check firing correctly on its own source file.

**Turning on `enforce_admins` broke `release.sh`, and the audit did not predict it.** A
freshly-created commit has no status checks, so it can no longer be pushed to `main`
directly — meaning the script would have bumped the manifest, created a tag locally, and
then failed, leaving exactly the half-completed release its own comments warn about. A
pre-mutation guard now detects protection and prints the PR route with the tree untouched.
**Wave C and wave D interact, and applying C without D's guard would have broken releases
silently.**

## 6. Cleanup plan

**Do now (minutes, no design decisions):** #3 `.env` + the substring bug, #4 branch
protection, and the one-line "PRIVATE" header. These are pure wins with no trade-offs.

**Do next, but they need your judgement (S1, S2):** both are disclosure questions, not code
questions. `git log` will say when those lines landed, which decides whether this is "fix
it" or "fix it and assume it has been seen". Do not let them sit because the code fixes are
more interesting.

**Then the wiring (#5, #6):** `release.sh` running its own gates, and one shared frontmatter
validator. #6 is the only item on this list fixing *live wrong behaviour*, and it is
dense-covered on both sides by 2,435 lines of existing tests.

**Then the big one (#7).** `render.py` is a real refactor with real breakage risk and wants
a fresh session, not the tail of another. The `_gen_hash` redefinition is **not optional** —
skip it and you silently disable the staleness gate while every test still passes.

**Deliberately not recommended:** chasing the anchor score. Items #7–#10 would move it a
lot and matter less than #1–#5, which move it barely at all. That divergence is the most
useful thing this baseline establishes.

---
*Generated by `/crucible:repo-audit`. Lenses frozen (version 1); anchor deterministic. Lens
claims were re-verified in the main loop — two were corrected (hook severity, `_utf8_stdio`
count) and one strengthened (`reliability.py`: all four function bodies byte-identical, and
the `test_verdict_parity` that looked like a counter-example tests something else entirely).
Raw per-lens output is gitignored under `docs/audits/.raw/`.*
