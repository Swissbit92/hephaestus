---
name: author-skill
description: Guide and scaffolder for writing a high-quality Claude Code skill or plugin. Use when the user asks to author, create, scaffold, or improve a skill, an agent, a command, or an MCP plugin — it lays out the high-leverage authoring patterns (with real exemplars) and creates a pre-structured SKILL.md. User-invoked, not automatic.
---

You help the author build a skill that is good *by construction* — not a blank file they
fill with prose. Scaffold the structure, then coach each section against the patterns
below. Cite the repo's own skills as live examples; don't theorize.

## Step 1 — Scaffold

Create the skeleton with the helper (pre-structured with every pattern below):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/new_skill.py" <kebab-name> --description "<trigger-focused one-liner>"
```

For an MCP-server plugin instead of a skill, copy `plugins/mcp-starter/` (it documents the
packaging: inline `mcpServers`, `userConfig` injection, uv server, first-run hook, `/setup`).

## Step 2 — Apply the patterns (each with a shipped exemplar in this repo)

1. **Exemplar-first negatives — lead with the failure mode.** Open with the worst, most
   common mistake as a concrete bad example, not positive advice. *Exemplar:*
   `skills/finish-branch/SKILL.md` opens its cleanup rules with the `-D` danger.
2. **Good/bad contrast pairs.** Show `# BAD … / # GOOD …` side by side — the delta teaches
   faster than either alone. *Exemplar:* the stub's Do-not block; `develop.md` tiering.
3. **Code-backed, not prose, for deterministic work.** If a step has one right answer, put
   it in a script and call it — don't ask the model to do it by hand. *Exemplars:*
   `scripts/bump_version.py`, `scripts/new_skill.py`, the `cms` scripts, and
   `sqlite-readonly`'s pure `validator.py`/`db.py` (so they're unit-testable).
4. **Hard-gate vs. best-effort — say which is which.** Mark steps that MUST pass to proceed
   distinctly from steps that degrade gracefully. *Exemplar:* `finish-branch` — "no green,
   no merge" is a hard gate; the merge/PR/keep/discard choice is the user's.
5. **Visible reasoning.** Where the skill makes a judgement, require it to show the why.
   *Exemplar:* `qa-gatekeeper` returns PASS/CONDITIONAL/REJECT *with findings*, not a bare
   verdict.
6. **Output schema.** Give the result a fixed, verifiable shape — specific enough to check
   mechanically. *Exemplar:* `sqlite-readonly` `read_query` → `{columns, rows,
   executed_sql}`.
7. **Progressive disclosure / token budget.** Keep SKILL.md light; push heavy reference into
   a sibling loaded on demand via `${CLAUDE_SKILL_DIR}/REFERENCE.md`. *Exemplars:* `cms`
   SKILL.md stays lean over its `scripts/`+`templates/`; `sqlite-readonly`'s schema render
   is token-budgeted; `mcp-starter` keeps the rationale in its README, not `plugin.json`.
8. **Embedded Lessons-Learned.** When a skill touches a fiddly external system, keep a short
   numbered "lessons" list inside it so a hard-won gotcha prevents the next mistake.
9. **Packaging gotcha (MCP plugins).** Declare `mcpServers` **inline in `plugin.json`**, not
   a `.mcp.json` — the installer skips dot-files, so a `.mcp.json` vanishes on
   `/plugin update`. *Exemplar:* `mcp-starter` / `sqlite-readonly`.

## Step 3 — Set the trigger deliberately

The `description:` frontmatter is what the model matches on for auto-invocation. Make it
specific. If the skill should be **user-invoked only** (like this one), say so in the
description and don't write a broad auto-trigger — an over-broad description misfires on
unrelated work.

## Step 4 — Make it testable, then register

- If you added a script, add tests under `tests/` (the scaffolder's helpers are pure stdlib
  for exactly this reason).
- For a new plugin, register it in `.claude-plugin/marketplace.json` and give it a README.
- Run `python3 -m pytest` and `scripts/check-public-safe.sh` before you finish.

## Guardrails

- **Scaffold, then coach — don't hand back a blank file.** The value is the structure plus
  the per-section critique against the patterns above.
- **Cite a real exemplar** from this repo for any pattern you recommend; if you can't, say
  so rather than inventing one.
- **Don't widen a skill's trigger** to "be helpful" — precise triggers beat broad ones.
