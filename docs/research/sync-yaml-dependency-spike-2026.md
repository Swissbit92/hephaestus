---
title: "sync.py and PyYAML — dependency spike (2026-08-22)"
status: completed
created: 2026-08-22
last_reviewed_on: 2026-08-22
review_in: 12 months
applies_to: hephaestus
ai_summary: "Timeboxed spike on whether cms's drift detector should depend on PyYAML instead of its hand-rolled YAML subset parser. Answer: no — but the parser has a real defect the dependency question was hiding. Probed against 8 realistic inputs, 3 fail SILENTLY: reordered keys and flow style both yield zero facts, and a trailing comment is swallowed into the regex, producing a pattern that can never match. All three look exactly like 'no drift found'. Recommends a ~20-line validation pass instead of the dependency. Read it before adding any third-party dependency to a plugin, or before trusting a sync run that reports nothing."
---

# sync.py and PyYAML — dependency spike

**Question:** should `cms`'s drift detector (`sync.py`) depend on PyYAML instead of the
"minimal YAML subset" parser it hand-rolls in `load_facts`?

**Answer: no — and the dependency question was hiding a defect worth more than the
dependency would have fixed.** Recommendation at the bottom.

Timeboxed spike. Read-only: nothing in `sync.py` was changed.

## What the parser actually does

Probed with eight inputs a user could plausibly write into `sync_facts.yaml`. Five parse
correctly. **Three fail, and all three fail silently.**

| Input | Result |
|---|---|
| Documented layout (`- name:` first) | ✅ correct |
| `expected_value: null` | ✅ correct |
| Value containing a colon (`'Status: (\w+)'`) | ✅ correct |
| Double-quoted value with an escape | ✅ correct |
| Anchor (`&n`) on a value | ⚠️ name becomes `&n v` — wrong, but visible |
| **Keys reordered** (`- pattern:` before `name:`) | ❌ **silently yields zero facts** |
| **Flow style** (`- {name: v, pattern: …}`) | ❌ **silently yields zero facts** |
| **Trailing comment** (`pattern: 'x(\d+)'  # note`) | ❌ **comment swallowed into the regex** |

The last one is the nastiest. The pattern becomes `'x(\d+)'   # one capture group`
— still a valid regex, and one that can never match anything. The fact is loaded, counted,
reported as active, and silently never fires.

## Why this is the same bug this repo keeps shipping

Every one of the three failures produces **"no drift"**, which is byte-for-byte what
success looks like. `sync` reports nothing, exits 0, and a reader concludes the docs agree.

That is the identical shape as the two defects fixed this week: the archive rule computing
age from mtime (worked on the author's machine, silently dead on every clone) and
`predictions.py`'s `--check` guard sitting behind `required=True` (the message existed,
was correct, and had never once been displayed). In all three cases the code was *present*
and *plausible* and the failure mode was **silence indistinguishable from success**.

A drift detector is a particularly bad place for it. Its entire output on a healthy repo is
nothing, so there is no baseline against which "nothing" looks wrong — exactly the
condition the `--baseline` rule was added to force people to check.

## Would PyYAML fix it?

All four, yes. It is a real, correct YAML parser and every case above is legal YAML.

But that is the wrong comparison, because **parsing was never the problem.** Five of eight
cases already parse correctly, and the documented format is narrow by design. What PyYAML
buys is tolerance of inputs the format does not document. What it costs is the repo's
central promise.

## What the dependency would cost

- **The pure-stdlib rule is load-bearing here, not aesthetic.** `CLAUDE.md` and the README
  both promise "no pip installs", and this is a *marketplace plugin*: a plugin that needs
  `pip install PyYAML` before its drift detector works is a different product with a
  different install story, on every machine that installs it.
- **There is no stdlib fallback.** Python ships no YAML parser
  ([Python Wiki](https://wiki.python.org/moin/YAML)), so this cannot be the `tomllib`
  pattern of "use the stdlib on new interpreters, degrade gracefully on old". It is a hard
  dependency or nothing.
- **Supply-chain surface on a tool that runs in CI** is a real cost, and the
  zero-dependency argument is strongest for exactly this shape of tool — one job, one file,
  runs inside someone else's pipeline.
- **The 3.9 floor.** Any pin has to hold across 3.9–3.13, which CI matrixes.

Alternatives were considered and change nothing structural: `ruamel.yaml` and
`pyyaml-pure` are still third-party packages, so they trade one dependency for another
rather than removing the objection.

## Recommendation: keep stdlib, make the failures loud

The cheap fix captures nearly all of the safety at none of the cost — roughly 20 lines,
no dependency:

1. **A non-empty `facts:` block that yields zero facts is an error, not silence.** This
   catches reordered keys and flow style together, without needing to parse either.
2. **Reject a value that still contains an unquoted ` #`** after stripping quotes — that is
   the swallowed-comment case, and it is trivially detectable.
3. **Reject unknown keys** inside a fact rather than ignoring them, so a typo
   (`patern:`) fails instead of producing a fact with no pattern.
4. **Report the fact count on every run**, so "0 facts" is visible in the output rather
   than inferred from an absence.

Items 1 and 4 are the important ones: together they make "the parser did not understand
your file" impossible to mistake for "your docs agree". Items 2 and 3 are cheap follow-ons.

If the format ever genuinely needs full YAML — nested structures, multi-document files,
merge keys — that is the point to revisit this, and the trigger should be a real user file
the subset cannot express, not the discomfort of hand-rolling. Until then the correct fix
is not a better parser; it is a parser that admits when it has failed.

## Method and limits

Eight hand-written inputs run directly against `sync.load_facts`, no mocking. Not
exhaustive — a property-based sweep over generated YAML would find more, and the anchor
case suggests other YAML syntax degrades to wrong-but-quiet rather than raising. The three
findings above are demonstrated, not estimated; anything beyond them is unmeasured.
