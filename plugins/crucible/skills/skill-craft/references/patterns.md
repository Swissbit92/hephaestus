# The authoring patterns, each with a shipped exemplar

Every pattern here is followed by a skill in this repo that actually uses it. Cite the
exemplar when you recommend the pattern; if you cannot find one, say so rather than
inventing it — a pattern with no shipped example is a preference wearing a rule's clothes.

1. **Exemplar-first negatives — lead with the failure mode.** Open with the worst, most
   common mistake as a concrete bad example, not with positive advice. *Exemplar:*
   `skills/finish-branch/SKILL.md` opens its cleanup rules with the `-D` danger.

2. **Good/bad contrast pairs.** Show `# BAD …` and `# GOOD …` side by side; the delta
   teaches faster than either alone. *Exemplar:* `second-brain`'s Do-not block, and the
   tiering in `commands/develop.md`.

3. **Code-backed, not prose, for deterministic work.** If a step has one right answer, put
   it in a script and call it rather than asking the model to do it by hand. This repo has
   measured the difference twice — a script the workflow runs caught a defect 3/3 where
   asking an agent to check caught it 2/6, and a prose review agent scored *identically to
   no agent at all*. *Exemplars:* `scripts/bump_version.py`, the plugin's
   `scripts/new_skill.py` and `scripts/skill_lint.py`, the `cms` scripts, `second-brain`'s
   `vault_graph.py`, and `sqlite-readonly`'s pure `validator.py`/`db.py`.

4. **Hard-gate vs. best-effort — say which is which.** Mark steps that MUST pass to proceed
   distinctly from steps that degrade gracefully. *Exemplar:* `finish-branch` — "no green,
   no merge" is a hard gate; the merge/PR/keep/discard choice is the user's.

5. **Visible reasoning.** Where the skill makes a judgement, require it to show why.
   *Exemplar:* `qa-gatekeeper` returns PASS/CONDITIONAL/REJECT *with findings*, never a
   bare verdict.

6. **Output schema.** Give the result a fixed, verifiable shape — specific enough to check
   mechanically. *Exemplar:* `sqlite-readonly`'s `read_query` → `{columns, rows,
   executed_sql}`.

7. **Progressive disclosure / token budget.** Keep `SKILL.md` light and push heavy
   reference into a sibling loaded on demand — this file is that pattern applied to
   itself. *Exemplars:* `cms` stays lean over its `scripts/`, `templates/` and
   `references/`; `sqlite-readonly`'s schema render is token-budgeted. `skill_lint`
   enforces the budget at 3000 tokens.

8. **Embedded lessons-learned.** When a skill touches a fiddly external system, keep a
   short numbered "lessons" list inside it, so a hard-won gotcha prevents the next
   mistake instead of being rediscovered.

9. **Packaging gotcha (MCP plugins).** Declare `mcpServers` **inline in `plugin.json`**,
   never in a `.mcp.json` — the installer skips dot-files, so a `.mcp.json` vanishes on
   `/plugin update`. *Exemplars:* `mcp-starter`, `sqlite-readonly`.

## Frontmatter that a runtime actually reads

Only `name` and `description` are required, and they are the whole routing surface: the
description is what a model matches on before it has seen anything else, so it must state
what the skill does *and when to reach for it*.

`disable-model-invocation: true` keeps a skill out of the startup prompt entirely, so it
costs no context until invoked by name. Use it when the skill represents a decision the
user must make first, not a capability the model should reach for on its own.

Anything beyond those three keys is a portability finding: unknown keys are inert in some
runtimes rather than rejected, so the cost is a silent behaviour difference in one agent
and not the other. `skill_lint` reports them.

## Registering a new skill

Skills are discovered by directory, so a new one needs no manifest entry — but the
frontmatter `name` must equal the directory name, or it is invoked under one name and
documents itself under another. Beyond that:

- add `tests/test_<name>.py` if it ships a script, and a `sys.path` entry in
  `tests/conftest.py` so the script imports as a flat module;
- append the skill to the plugin's `description` in `.claude-plugin/plugin.json` and bump
  its `version` — the pin is what triggers updates for installed users;
- extend the crucible clause in `.claude-plugin/marketplace.json` for a headline
  capability;
- add a `CHANGELOG.md` entry under `[Unreleased]`.
