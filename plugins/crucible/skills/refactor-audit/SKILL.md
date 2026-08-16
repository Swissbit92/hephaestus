---
name: refactor-audit
description: Audit a body of recent work — a git range, a branch, or the working diff — for what it would take to reach production quality, and return a ranked report split into what an agent can fix unattended and what needs a human decision. Use when asked whether recent changes have cleanup potential, design problems, or maintainability and extendability debt. Not a bug hunt (that is code review), and not a whole-repo sweep (that is repo-audit).
---

You turn *"is there anything to clean up in what we just built?"* into a ranked, evidence-
backed list its author can work through in order. The ranking is most of the value: a flat
list of thirty observations gets skimmed and dropped, and the two findings that mattered go
with it.

## When this applies

The unit is **a change**, not a repository: a commit range, a branch about to merge, or the
uncommitted working diff.

- Looking for defects — wrong output, a crash, an injection? That is a code review, and it
  asks different questions of the same diff.
- Want the standing health of a whole tree, trended over time? That is `repo-audit`, which
  anchors on deterministic metrics precisely because whole-repo judgement wobbles.
- Deciding whether the change may merge at all? That is `finish-branch`; this skill informs
  that decision but never makes it.

Run it before the merge, while the author still holds the context to act on it.

## The standard you are auditing against

"Production quality" means code a team can own, extend and operate without its author in
the room. Two rails keep that from becoming taste:

**Every finding names the standard it fails.** "No silent failure at a trust boundary" is a
finding. "I would have named this differently" is not. Where the project has no written rule
and you are applying your own, say so — an author can argue with a stated standard and
cannot argue with a preference presented as a fact.

**The project's own conventions outrank generic best practice, always.** If its rules say
service methods must not catch exceptions, then "add defensive error handling" is *wrong
here*, however standard it sounds elsewhere. This is the failure mode that discredits an
entire audit: re-litigating a settled decision invites the author to discard the whole
report, including the findings that were right.

Prototype code is not automatically deficient. Audit it against where it is going, and
distinguish "acceptable now, blocks production" from "wrong now".

## The workflow

1. **Fix the scope before reading any code.** Establish the range and state it in the
   report header, so the audit's coverage is falsifiable rather than implied.

   ```bash
   git log --oneline <base>..HEAD
   git diff --stat <base>..HEAD
   git diff --name-status <base>..HEAD
   git status --short
   ```

   Re-read `HEAD` rather than trusting any summary already in context — the author may
   have committed since. Split **added** files from **modified** ones: an added file is a
   new subsystem and you audit its design; a modified file is existing code and you audit
   the blast radius on everything sharing it.

2. **Load intent before the diff.** Start with the routing table rather than opening
   candidates — searching by opening costs the full text of everything you opened and
   were wrong about:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/cms/scripts/triage.py" --repo .
   ```

   Then read the repo's agent-context and convention files, and the decision records
   the table points at. Extract four things: the premise the work was
   done under, the decisions already made, the conventions that override generic advice,
   and how the code is verified. State the premise in the report and audit *inside* it.

3. **Gather evidence — no finding without it.**
   - **Prove duplication.** Diff the suspected copy against its original and report the
     measurement ("byte-identical", "9 of 140 lines differ"). Never "appears to be copied".
   - **Before calling anything dead, search every surface that could reach it** — callers,
     templates, config, DI wiring, reflection, string-dispatched handlers, docs that
     instruct a human to run it. List where you looked, so the author can spot the surface
     you did not know about.
   - **Anchor every finding at `file:line`.** If you cannot point at it, it is a suspicion
     and belongs in a separate list, labelled as one.
   - **Separate latent from live.** "Harmless today because nothing calls it twice — which
     is exactly why it will not stay harmless" is a real and rankable finding, and it is
     not the same as a defect that is biting now.

4. **Rank on two axes, then split by who can act.** Order by *cost of leaving it* against
   *cost of fixing it* — the cheap-to-fix, expensive-to-keep items come first, and a
   finding that is expensive both ways goes last with that trade-off stated.

   Then split the ranked list in two, because they are consumed differently:
   - **An agent can fix this unattended** — mechanical, reversible, verifiable by the
     existing tests.
   - **This needs a human decision** — it changes a public contract, contradicts a recorded
     decision, or trades one property for another.

5. **Report the shape of the change, not only its faults.** Name what the work got right,
   and say plainly when the answer is "nothing worth doing". An audit that cannot return
   an empty list is not measuring anything.

## Anti-patterns

- **The undifferentiated list.** Thirty findings in no order is a wall the author bounces
  off. If you cannot rank them, you do not yet understand them well enough to report them.
- **Auditing the diff without the decisions.** Produces confident findings that were
  deliberate trade-offs, and costs the credibility of everything around them.
- **"Consider extracting this."** Extraction has a risk to the original that a suggestion
  does not carry. Offer the option, name that risk, and offer the cheaper partial split
  that captures most of the value without it.
- **Counting instead of judging.** Line counts and complexity scores are inputs. A 400-line
  function that is one flat dispatch table is fine; a 40-line one holding three interleaved
  concerns is not.
- **Fixing while auditing.** Produce the ranked list first even when the ask is "just fix
  it" — the ordering is the deliverable, and some entries are the author's call.

Pairs with `repo-audit` when the question widens from this change to the whole tree, and
with `finish-branch`, which decides whether the work merges.
