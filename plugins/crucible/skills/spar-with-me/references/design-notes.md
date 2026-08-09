# spar-with-me — design notes and what has actually been measured

Loaded only when changing this skill or deciding whether to keep it. `SKILL.md` carries the
instructions; the reasoning lives here so it does not enter context on every invocation.

## Why this isn't role-play

hephaestus rejects the sequential role-play waterfall — [VISION.md](../../../../../VISION.md)
documents the degradation, and "sparring partner" could easily be that in costume. It isn't,
for the same reason `repo-audit` isn't: there is **one** conversational agent, and the only
fan-out is read-only, independent, parallel research over a static tree and the open web. No
role hands state to another role. The value is verification of what is already known, before
an opinion is formed — not a committee pretending to think.

## Why the skill exists at all (the routing diagnosis)

The complaint that started it was that `grill-me` felt too aggressive to reach for. It was not
miscalibrated on intensity but on **lifecycle stage**: every phase in it attacks a position,
which only works if the user has one. Its description ended with *"or needs a thinking partner
on a non-trivial choice"* — and skills route on description, so that clause pulled it into
exactly the half-formed-idea moments it is worst at. The felt aggression was a routing bug.
Hence a sibling plus a one-clause description fix, rather than a rewrite that would have
destroyed the only tool in the plugin that forces a falsifiable tripwire.

## What has been measured — and it is not flattering

All numbers k=10 per arm, single-turn `claude -p`, small purpose-built fixtures.

| Property | With skill | Control (no skill) | Verdict |
|---|---|---|---|
| Stays read-only | 10/10 | 10/10 | no effect — *does not break it*, not *causes it* |
| Finds the repo's own ADR | 10/10 | 10/10 | no effect |
| Asks the discriminating question | 3/10 | 3/10 | **defect confirmed**, no lift |
| …after reordering the step earlier | 3/10 | 4/10 | the fix moved nothing; reverted |

**Zero measured causal effect on anything.** Read that honestly before defending any part of
this file.

### Why that is not the whole story

The instrument only reaches cases where the base model already succeeds, so the finding is
weaker than it looks:

- **Toy repos.** The internal-research fixture was three files with one ADR, where "read the
  decisions" is trivial. On a real repo with dozens of ADRs and years of settled questions,
  the base rate for "did it check what we already rejected?" is plausibly much lower. That
  version was never tested.
- **Single turn.** Constraint decay — the thing rule 1 exists for — is a *long conversation*
  phenomenon. One turn is the case where it cannot fail.
- **Rule 3 is untested entirely.** Holding a position needs pushback, which needs a second
  turn, which the harness cannot represent. It is also the property where published base rates
  are genuinely poor (models flip correct→incorrect on user rebuttal roughly 1 in 7 times), so
  it is the most likely place for real lift — and the one place nothing is known.

Absence of evidence is weak evidence of absence when the instrument is pointed at the easy
cases.

## The Q&A defect is real and currently out of reach

Rule 4 fires 3/10. Reordering it earlier and removing its permission to skip changed nothing,
because that was a **wording** change dressed as a placement change — see the 2026-08-09 entry
in [LESSONS_LEARNED.md](../../../../../docs/LESSONS_LEARNED.md). Fixing it properly needs a
turn boundary this skill cannot create, and the single-shot harness cannot represent *ask and
wait* at all — it only sees whether a question was emitted. Recorded rather than papered over.

## The keep-or-delete test

Use it on ten real questions in a real repo. If you cannot point to one session where it
produced something a bare question would not have, delete it. The measurements above cannot
settle that, because they never tested the conditions it was built for.
