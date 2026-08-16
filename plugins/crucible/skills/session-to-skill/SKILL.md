---
name: session-to-skill
description: Distil the session that just happened into a reusable skill — identify the repeatable process underneath the specific task, generalise it away from this project's nouns, confirm the abstraction with the user, then scaffold and install it. Use when the user asks to capture, save, or turn this conversation into a skill. For writing a skill you have already decided on, use author-skill instead.
disable-model-invocation: true
---

You look backwards at what just happened and extract the part worth keeping. `author-skill`
starts from an intention someone already has; this starts from a transcript and has to find
whether there is a skill in it at all.

## When this applies

The user says some version of "save this", "capture how we did that", or "make this a
skill". It is always user-invoked — a session is not evidence that its process generalises,
and offering to immortalise every conversation is noise.

Honest first move: **decide whether there is anything here**. A session that was one lookup,
or that only worked because of this repository's particulars, yields no skill. Saying so
costs one sentence; a library of thin, near-duplicate skills costs a routing decision on
every future session, forever.

## Generalise the process, not the task

This is the whole discipline, and the failure is always the same shape: the session is
*about* something, and the captured skill preserves that something instead of the method.

A session spent mapping one application's architecture and producing a diagram should become
"when asked to map a system's architecture: gather X, verify against the code, render as Y" —
reusable anywhere. What it must not become is a skill that hardcodes that application's
module names, which is a document about one codebase wearing a skill's clothes.

Keep: the sequence, the decision rules, the commands and their gotchas, the verification
step, the traps that cost time. Drop: the subject matter, one-off values, transient status,
and any name that only means something inside this project. Never carry over secrets,
tokens, or pasted logs — reference a path instead of embedding its contents.

The test: **could someone in an unrelated repository follow this?** If not, it is either not
generic yet, or it belongs in that project's own `.claude/` rather than in a plugin.

## The workflow

1. **Name the candidates.** Usually one, occasionally two. For each, draft the `name`, the
   trigger-focused `description`, and a section outline. Say which parts of the session you
   are discarding as specifics — that is the step where a bad abstraction becomes visible.

2. **Confirm before writing anything.** Present the abstraction and let the user correct it.
   They know whether the method generalises; you only know that it worked once. This is the
   cheapest possible moment to find out the answer is no.

3. **Scaffold it:**

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/new_skill.py" <kebab-name> --description "<trigger-focused one-liner>"
   ```

4. **Write it as instructions, not as a summary.** A future agent follows this without
   re-deriving it, so a wrong step is worse than a missing one. Everything asserted must be
   something you actually observed in the session — if a command was never run, say it is
   untried rather than presenting it as known-good.

5. **Place it deliberately.** A generic craft technique belongs in a plugin; anything that
   depends on one codebase's conventions belongs in that repository's `.claude/skills/`.
   Placing a project-shaped skill in a shared plugin is how a generic library acquires
   domain knowledge nobody else can use.

6. **Set the trigger.** Model-invocable when the description alone should be enough for an
   agent to reach for it; `disable-model-invocation: true` when it represents a decision the
   user must make first.

7. **Verify it loads, then lint it:**

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/skill_lint.py" --strict
   ```

   A new skill distilled from a session is the most likely thing in the library to overlap
   an existing one, because sessions repeat. The linter says so before the duplication is
   someone else's problem.

## Anti-patterns

- **Capturing the transcript.** A narrative of what happened is not a procedure. If it reads
  as history rather than instruction, it is not a skill yet.
- **The skill that only fits its birthplace.** Detectable by the test above; usually fixable
  by raising one level of abstraction, occasionally fixable only by not shipping it.
- **Writing it before confirming the abstraction.** Cheap to ask, expensive to maintain a
  skill nobody reaches for.
- **Documenting what was never observed.** The session is the evidence; anything beyond it is
  a guess with a skill's authority.
- **One skill per session.** The library's usefulness falls as its routing decisions multiply.

Pairs with `author-skill`, which carries the authoring patterns once you know what you are
writing.
