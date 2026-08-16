# cms shared state — resolution, migration, and what lives where

The rule is in `SKILL.md`: runtime state is never written inside the plugin. This is the
mechanism behind it.

## Resolution order

1. `CMS_STATE_DIR` env var, if set — used by the test suite to isolate state writes,
   since `common.py` resolves and creates the directory at import time.
2. `${CLAUDE_PLUGIN_DATA}/cms-state` when running as a plugin.
3. `~/.claude/cms-state` — the default in ordinary use, since neither env var is normally
   set.

## Migration from older versions

State written by older versions is migrated out of `<skill>/state/` on first run and the
legacy copy removed. The migration is **non-destructive**: an existing file at the new
location always wins, so a repo that has already accumulated history under the new path
never has it overwritten by a stale copy shipped in a plugin update.

## The two kinds of file

| File | Kind | Where |
|---|---|---|
| `size_history.json` | **runtime state** — per-repo CLAUDE.md line-count history, backing the "grew >20%" warning | the resolved state dir above |
| `sync_facts.yaml` | **shipped config** — regex allowlist of known-drift facts; ships empty and grows as drift is found | versioned with the plugin at `<skill>/state/`, which is why `sync --facts` defaults there |

Anything added here follows the same split: versioned starters inside the plugin,
accumulated runtime data outside it. `sync_facts.yaml` must stay free of
ecosystem-specific tokens — it is shipped, so `tests/test_seam.py` scans it.

## Why not simply write beside the skill

Two failure modes, and both bite in practice:

- **A plugin update overwrites the plugin directory.** State kept there is lost on every
  upgrade, which is the moment it is least expected and hardest to notice.
- **State records one entry per repository.** Inside a generic (Tier A) plugin that makes
  the plugin carry domain content, which `tests/test_seam.py` rejects under ADR-001. The
  seam is enforced mechanically rather than by convention precisely because this kind of
  leak is invisible in review.
