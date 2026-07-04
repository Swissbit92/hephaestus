---
name: flag-gate
description: Default-OFF feature-flag rollout with instant revert. Use when the user is shipping a behavioral change to a system in use, wants to roll out safely, add a feature flag, gate a change behind a flag, keep a legacy path for instant rollback, flip a change incrementally, or retire a flag after a soak. Pairs with eval-first (the gate that authorizes the flip).
---

You help the user ship behavioral changes safely with **default-OFF feature flags and instant revert**. The principle: a change to a system in use is unproven until measured, so the live path must stay unchanged until a gate says flip — and reverting must be flipping a flag, not redeploying.

## When this applies

Any behavioral change to a system that's already running: prompt/model swaps, new agent behavior, retrieval changes, a reworked code path. If flipping it back would require a code rollback or redeploy, it isn't flag-gated yet.

## The rules

1. **Default OFF.** The new behavior is gated; the default is the existing, byte-identical legacy path. Nothing changes for live traffic until you flip the flag.
2. **Don't touch the legacy path.** Add the flag *around* the new path; leave the old one exactly as it was. Instant revert depends on the legacy path still being there and unchanged — refactoring it while flagging defeats the purpose.
3. **Flip on a gate, not a hunch.** Don't flip globally until `/crucible:eval-first` says match-or-beat against the frozen baseline. Use a per-scope allowlist (per-user, per-tenant, per-repo) to flip incrementally and watch before going global.
4. **Revert = flip the flag OFF.** No code rollback, no redeploy. The flag is the kill switch; that's the entire value. If revert needs anything more, the change wasn't flag-gated.
5. **Assert the default in a test.** A flag that silently defaults ON defeats the safety. Test the default value *env-independently* — assert the declared default in code, not the value after the environment resolves it (an env var set in the test shell will mask a wrong default).
6. **Retire after soak.** Once the flag has been ON with no regressions through a soak window, delete the legacy path and the flag. Set an earliest-retire date when you create it. Permanent flags become flag debt — branching complexity nobody removes.
7. **The failure branch gets a deadline too.** The retire date in rule 6 only covers the flag that *wins*. Set a second date at creation for the flag that *loses*: when the eval comes back worse, by that date the change is either fixed and re-gated, or the flag **and its now-dead new path are deleted**. A gate that failed and was left OFF with the new code still in the tree is the same flag debt as a permanent ON flag — a branch kept alive that will never flip. "Parked" with no date is how it rots there.

## The lifecycle, end to end

```
add flag (default OFF, legacy untouched)
  → ship (live path unchanged)
  → /crucible:eval-first: candidate vs frozen baseline
  → match-or-beat? flip per-scope → watch → flip global
  → worse? leave OFF → fix-and-re-gate OR delete flag + dead new path by the failure-decision date (never park indefinitely)
  → soak clean → delete legacy path + flag (retire by the date you set)
```

## Anti-patterns

- **Default ON** — the change is live before it's proven; there's no safe state to revert to.
- **Refactoring the legacy path while adding the flag** — now revert isn't byte-identical and "flip it off" no longer restores the old behavior.
- **Flipping before the eval gate** — shipping on a hunch is the thing flags exist to prevent.
- **Permanent flags** — every un-retired flag doubles a code path forever. Retire on schedule.
- **Indefinitely parked flags** — a flag whose eval came back worse, left OFF with its new path still in the tree and no decision date. "Parked" is flag debt wearing a nicer word: set a fix-or-delete date at creation, and when it arrives, one of the two paths gets deleted. A dark, built, un-owned code branch is exactly what accretes into stacked `if flag:` god-functions.
- **Non-revertible "flags"** — a flag in front of a one-way state migration isn't a kill switch; flipping it off won't undo the migration.

This is the rollout half of safe iteration; `/crucible:eval-first` is the measurement half. Use them together: eval-first decides *whether* to flip, flag-gate makes the flip and its reversal cost nothing.
