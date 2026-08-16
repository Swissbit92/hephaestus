---
name: skill-craft
description: Build, distil and check agent skills. Three modes — author (scaffold and coach a skill you have decided to write), distil (turn the session that just happened into a reusable skill, generalising the process rather than snapshotting the task), and lint (check a library for budget overruns and skills that have drifted into saying the same thing). Use when asked to create, scaffold, improve, capture or save a skill, an agent, a command or an MCP plugin, or to check a skill library's health. User-invoked, not automatic.
disable-model-invocation: true
---

You help build a skill that is good *by construction* — scaffolded, then coached section by
section — and you refuse to build one when the honest answer is that there is nothing here
worth keeping.

## Three modes

| Mode | You start from | First question |
|---|---|---|
| **author** | an intention the user already has | what shape should this take? |
| **distil** | a transcript of what just happened | is there a skill in this at all? |
| **lint** | an existing library | what has drifted? |

They share a destination — a `SKILL.md` that a future agent follows without checking — so
they share the patterns in
[references/patterns.md](references/patterns.md). Load that file when you start writing;
it carries the nine authoring patterns with a shipped exemplar for each, the frontmatter
rules, and what registering a skill requires.

## The refusal comes first

**Most sessions do not contain a skill, and most "wouldn't it be useful if…" ideas are not
one either.** A session that was a single lookup, or that only worked because of one
repository's particulars, yields nothing reusable. Saying so costs a sentence. Shipping it
costs a routing decision on every future session, forever — and that cost is measured:
overlapping skills make the choice between them arbitrary, which is why `lint` exists.

The test, in both directions: **could someone in an unrelated repository follow this?** If
not, it is either not general yet, or it belongs in that project's own `.claude/skills/`
rather than in a plugin.

## `author` — forward from an intention

1. **Scaffold, don't hand back a blank file.**

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/new_skill.py" <kebab-name> --description "<trigger-focused one-liner>"
   ```

   For an MCP-server plugin rather than a skill, copy `plugins/mcp-starter/` — it documents
   the packaging that is easy to get wrong.

2. **Coach each section against the patterns**, citing the repo's own skills as live
   examples. Theorising about what a good skill looks like, next to fourteen shipped ones,
   is a waste of the evidence lying around.

3. **Set the trigger deliberately.** The `description` is the only thing a model sees
   before deciding to load the skill. Precise beats broad: an over-wide description
   misfires on unrelated work, and a skill that fires when it should not is worse than one
   that never fires, because it is harder to notice.

4. **Make it testable, then register it** — see the reference for what registration
   touches.

## `distil` — backward from a session

The discipline is one sentence: **generalise the process, don't snapshot the task.** The
failure is always the same shape — the session is *about* something, and the captured skill
preserves that something instead of the method.

A session spent mapping one application's architecture and producing a diagram should
become "when asked to map a system's architecture: gather X, verify against the code,
render as Y". What it must not become is a skill hardcoding that application's module
names, which is a document about one codebase wearing a skill's clothes.

Keep the sequence, the decision rules, the commands and their gotchas, the verification
step, and the traps that cost time. Drop the subject matter, one-off values, transient
status, and any name that means nothing outside this project. Never carry over secrets or
pasted logs — reference a path instead of embedding its contents.

Then: **name the candidate, say what you are discarding as specifics, and confirm before
writing anything.** Naming the discards is where a bad abstraction becomes visible, and
confirmation is the cheapest possible moment to hear "no, that is not the reusable part".

Anything the skill asserts must be something the session actually showed. If a command was
never run, say it is untried rather than presenting it as known-good — a future agent
follows this without checking, so a confident wrong step is worse than a missing one.

## `lint` — check it against the library

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/skill_lint.py" --strict [--show-duplicates]
```

Exit `0` clean · `1` a finding at the failing severity · `2` **could not determine** — no
skills found, which is not a pass.

It reports two things review cannot: a `SKILL.md` past its context budget, and two skills
whose descriptions or prose have converged. A skill written in either of the other modes is
the most likely thing in a library to overlap something already there — `author` because
the need felt novel, `distil` because sessions repeat — so run it before you finish, not
after someone else trips over it.

A finding names the fix. An oversized skill wants a `references/` sibling, not a rewrite. A
duplicated passage wants one of the two to link the other. **Fix the skill, never the
threshold** — the thresholds are pinned by tests precisely so that relaxing one is a
visible act.

## Anti-patterns

- **Capturing the transcript.** A narrative of what happened is not a procedure. If it
  reads as history rather than instruction, it is not a skill yet.
- **The blank scaffold.** Handing back a stub is the easy half; the value is the structure
  plus the per-section critique.
- **Widening a trigger to be helpful.** Precise descriptions beat broad ones, and a
  mis-firing skill is expensive to diagnose.
- **A pattern with no exemplar.** If nothing in the library does it, it is untested advice.
- **One skill per session.** The library's usefulness falls as its routing decisions
  multiply.
- **Documenting what was never observed.** The session is the evidence; anything past it is
  a guess carrying a skill's authority.

Pairs with `cms` when the artefact is documentation rather than a skill, and with the
`curate` command, which runs `lint` across the whole library on a schedule rather than at
the moment of writing.
