# Invariants — turning a standing constraint into a check

Loaded when wiring up `docs/INVARIANTS.md`. `SKILL.md` carries the summary; the reasoning and
worked examples live here.

## The problem this solves

A constraint stated once at the start of a task is at its most memorable exactly when it is
least likely to be violated, and least memorable exactly when it matters. By the time the
work reaches the point where "mobile-first" or "no new dependencies" would be broken, that
sentence is the oldest thing in the conversation and is competing with everything said since.

Two properties of that decay are worth knowing, because they shape the fix:

- **Prohibitions fade faster than requirements.** "Never do X" degrades more sharply over a
  long session than "always do Y". Where you can, state an invariant as something to do
  rather than something to avoid.
- **Compaction does not reliably restore it.** Summarising the conversation is as likely to
  drop the constraint as to preserve it. So "it'll be in the summary" is not a plan.

The conclusion is uncomfortable but freeing: **do not solve this by remembering harder.** The
mechanism doing the forgetting is the same one being asked to remember. Move the constraint
somewhere that does not forget.

## Spec vs. invariant

These get confused constantly, and the confusion is the root cause.

| | Feature spec | Invariant |
|---|---|---|
| Scope | One change | All changes |
| Lifespan | Dies at merge | Outlives every task |
| Done means | It was built | Nothing — it never finishes |
| Lives in | The branch, the PR | `docs/INVARIANTS.md` |

Filing a standing constraint inside a task document is why standing constraints disappear:
the document is finished, so the constraint reads as finished too. If it should still bind
someone six months from now who never read that document, it is an invariant.

## The pipeline

`PROSE` → `FALSIFIABLE` → `CHECK` → `ENFORCED`

**Prose.** Write it down. Weakest form, but the entry point — an unwritten constraint cannot
be wired up later.

**Falsifiable.** Rewrite it so a machine could disagree. `WHEN <trigger> THE SYSTEM SHALL
<behaviour>`, or Given/When/Then. This step does most of the work, because it forces the
vagueness out into the open:

| Prose | Falsifiable |
|---|---|
| "Mobile-first" | WHEN the viewport is 375px wide THE SYSTEM SHALL NOT scroll horizontally |
| "No new dependencies" | WHEN the dependency manifest gains an entry THE SYSTEM SHALL require a matching decision record |
| "Stay backward compatible" | WHEN a public signature changes THE SYSTEM SHALL fail until the change is recorded as breaking |
| "Keep it fast" | *(not yet falsifiable — fast at what, measured how, over which input?)* |

That last row is the point. If you cannot write the falsifiable form, you have not been
specific enough to hold anyone to it, and the honest move is to say so in the entry rather
than pretend a check is coming.

**Check.** The falsifiable form, executed. A test, a lint rule, a script — whatever fails
loudly. Put the path in the entry's `Check:` field.

**Enforced.** The workflow runs it every milestone. Nobody has to remember it, which was the
entire objective.

## Where checks live

**In your repository, not in the tooling.** What counts as a violation of "backward
compatible" is a local judgement — which surfaces are public, what deprecation you allow —
and a generic plugin has no business deciding that for you. The mechanism runs whatever you
wire; it never ships opinions about your constraints.

A check is any executable that exits non-zero on violation. Keep them small and specific;
one invariant, one check.

## What is deliberately not automated

**Generating a check from prose.** It would produce plausible-looking checks that assert
something adjacent to what you meant, and a check that passes for the wrong reason is worse
than no check — it converts an open question into a false answer. The conversion step stays
manual because that is where the thinking is.

**Erroring on an unwired invariant.** `cms check` warns; it never blocks. A gate on an
unwired *intent* teaches people to stop recording intents, which costs more than the missing
check.

**Dating them.** No `last_reviewed_on` / `review_in`. Those ask "is this still accurate?" on a
timer — right for a description of the system, wrong for a rule about it. A constraint does
not expire because nobody looked at it, and a review date on one manufactures exactly the rot
the file exists to prevent. Retirement is a decision someone writes down.

## Retiring one

Set `Status: retired` and leave it in place. The reasoning stays useful — the next person to
propose the same thing deserves to find out it was considered and dropped, and why. Deleting
the entry loses that and invites the argument to be had again from scratch.
