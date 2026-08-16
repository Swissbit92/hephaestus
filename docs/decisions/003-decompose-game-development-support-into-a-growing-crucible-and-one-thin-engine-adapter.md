---
title: Decompose game-development support into a growing crucible and one thin engine adapter
status: Accepted
created: 2026-08-16
last_reviewed_on: 2026-08-16
review_in: 24 months
applies_to: hephaestus
ai_summary: "Settles how hephaestus takes on domain-specific (game-development) tooling without becoming a knowledge marketplace. Rejects a game-development plugin set and adopts two plugins instead: crucible grows four domain-neutral capabilities (declarable evidence classes with a three-valued outcome, sync-branch, verify-before-retry and idempotency keys in act-for-real, the BLOCKED stop-signal), and one new thin `forge-unity` adapter carries only what is durably Unity. Project-specific commands never ship: a repo-side `.forge/adapter.json` maps the plugin's abstract verbs onto that project's own command names, so the plugin ships the contract and the detector while the project ships the implementation. Records the evidence — the natural experiment in a first-generation game repo where an engine knowledge layer was built and then discarded, the saturated Unity-knowledge shelf, and the 2026 verified-tool-call literature that independently derives the same verification rules. Read it before adding any domain plugin, before writing engine knowledge content, or when deciding where project-specific tooling belongs. Two preconditions block the work and one capability question is unverified."
---

# ADR-003: Decompose game-development support into a growing crucible and one thin engine adapter

## Context

hephaestus ships five Tier-A generic plugins. The open question is whether it should
also carry **domain-specific** tooling — concretely, a game-development plugin set
extracted from a private, third-party networked Unity 6 game worked with a
13-skill in-repo harness.

Three constraints frame the answer, and all three were confirmed rather than assumed:

- **A second engine or game is coming**, and **public users are the goal**. Attribution
  for the extracted material is signed off.
- The operator wants **one marketplace**, not today's mixture of hephaestus plus
  per-project skill folders plus a symlinked local library.
- [ADR-002](002-publish-hephaestus-publicly-retiring-the-private-distribution-non-goal.md)
  made the repo public, so anything extracted is published irreversibly.

### What the game repo actually contains

Triaged by what each skill is bound to, not by what it is named:

| Binding | Skills | Portable? |
|---|---|---|
| Nothing (pure git / process) | `feature-sync`, `work-findings`, `discord-bridge` | fully |
| Project vault + chat conventions | `feature-kickoff`, `feature-gate` | the evidence table only |
| Unity, durably | `code-audit` §1 (`.meta` orphans, unimported scripts, unwired components) | yes |
| Unity + one third-party package | `editor-client`, `editor-fix-console` | with work |
| Unity + APFS, macOS-only | `editor-parallel` | partially |
| Photon Fusion, this game's session identity | `game-multiplayer` | no |
| **Thirteen observation commands defined in that game's own C#** | its trace/capture skill | **never** |

The finding that decides the shape: **the most reusable material is not the
game-specific material.** The genuinely game-shaped skills are the least portable, and
the observation skill cannot be extracted at all — it documents an API only one
repository on earth implements.

### The natural experiment already ran

That game has a **first-generation** repository, worked from 2026-04-11 to 2026-05-14,
and its `.claude/` is a complete, fully-formed game-development plugin:
`unity-code-reviewer` and `project-hygiene-enforcer` agents, three path-scoped
`rules/unity-*.md` files, three Unity knowledge skills, a PostToolUse compile hook, a
PreToolUse file guard, a SessionStart state-injection hook, an MCP launcher with
PowerShell variants, and early copies of `cms`, `grill-me` and `develop`.

hephaestus was born 2026-06-17 carrying those last three. The successor game repo
(2026-05-23 → present) carried almost none of the rest:

| The first-generation repo had | Survived into the successor |
|---|---|
| 2 Unity agents | no |
| 3 `rules/unity-*.md` + 3 knowledge skills | no — a grep for `fake-null`, `FindObjectOfType`, `Camera.main` across `.claude/` returns nothing |
| `check-compile` PostToolUse hook | no — replaced by an explicit recompile gate |
| `protect-files`, `inject-sprint-state` hooks | no |
| MCP server registered | no — `.mcp.json` deliberately deleted, reclaiming ~3,487 tokens per request against ~467 actually used |
| — | one hook survives: a vault-integrity checker, which is not about Unity |

**The engine knowledge layer was built, shipped, and discarded. The verification
discipline was built afterwards and grew.** That is local evidence, and it outranks
any market survey.

### What the field ships, and what it does not

Every published game plugin surveyed is a **knowledge pack** — API patterns and
gotchas keyed to an engine release: a 67-skill cross-engine collection with an
engine-detecting router, a 21-skill Unity toolkit, a 20+-skill mirror of Unity 6.3 LTS
docs. Unity itself now ships an official MCP server and an in-editor agent in open
beta. Public-skill quality averages 6.2/12; curated skills raise agent pass rates by
16.2 points.

Nobody occupies the **verification** lane. The research does: the 2026 work on
verified tool calls under non-atomic failures frames the problem as *the response
channel and the effect channel are separate*, and derives three requirements that the
game repo had already reached empirically:

| Published requirement | The game repo's own wording |
|---|---|
| Effect–response separation | "A call can succeed and still do nothing — verify by filesystem artefact, not by the tool's return value" |
| Verify-before-retry | "Stop and surface it rather than retry — retrying burns turns and produces contradictory evidence" |
| Idempotent execution with dedup keys | *absent* |

Reported: 100% task success against a baseline degrading 92% → 64%, and duplicate
side-effects falling from 20–72% to 0–20%, with an ablation showing **verification
alone drove most of the gain**.

### A defect this work must fix

`crucible@hephaestus` is enabled globally in user settings, so it loads in every
session on the game repo. A search of that repo's `.claude/`, its vault and its
`CLAUDE.md` for `crucible` or `hephaestus` returns **zero hits**. Two workflow spines
therefore load side by side with no declared relationship, and `finish-branch`'s
"tests green, no regression" gate is a literal no-op there — the project has no test
assemblies. The friction is mechanical, not stylistic.

## Decision

**Reject a game-development plugin set. Grow `crucible`, add exactly one thin engine
adapter, and put the project-specific half behind a repo-side contract.** The
marketplace goes from five plugins to six.

### 1 · `crucible` grows — four domain-neutral additions

1. **Declarable evidence classes.** `finish-branch` and `qa-gatekeeper` stop hardcoding
   a test command and read what the repository declares as proof. The outcome is
   **three-valued — pass / fail / could-not-check** — and the third must never resolve
   silently to the first. Two independent sources require that third state: the
   verifier literature returns True/False/Unknown, and the `cpp26-adapter` plugin
   separates a genuine bug from `compiler-lag`. The game repo already states the same
   rule for platforms: *"unverifiable-on-this-machine is a state, not a pass."*
2. **`sync-branch`**, lifted from the game repo's `feature-sync`. It fills the hole
   between `start-branch` and `finish-branch`, carries the `git merge-tree` dry-run
   classification, and fires **on trigger, not on position** — before expensive
   evidence, and always immediately before the gate.
3. **Verify-before-retry and idempotency keys**, folded into `act-for-real`. The first
   two published requirements are already that skill's thesis; the dedup key is absent
   and is what stops a blind retry from sending money twice.
4. **The BLOCKED stop-signal protocol** — a fixed-format first line naming one cause
   and one action, then a halt on everything dependent.

### 2 · `forge-unity` — one new plugin, deliberately thin

Carries only what is genuinely Unity and does not rot: the editor client, the
asset-integrity sweep (`.meta` orphans, unimported scripts, unwired components), the
modal-dialog guard, the known-blocker table, and a `/forge-init` command.

**It ships no always-resident engine knowledge.** Knowledge is permitted only as a
lookup subordinate to a ground-truth verifier — the shape `cpp26-adapter` uses, and the
shape the game repo already reaches for in *"vendor docs are not authoritative over the
vendor tree — grep the vendor folder to confirm the API exists."* Always-loaded rule
files are the artifact that first-generation repo proved does not survive.

### 3 · The adapter contract — how a marketplace carries project-specific work

A plugin can never ship another project's `trace_start` command. So the seam inverts: **the plugin ships the
contract and the detector; the project ships the implementation.** `/forge-init`
scaffolds a repo-side `.forge/adapter.json` mapping abstract verbs onto that project's
real command names (`capture.sheet → <that project's capture command>`). The plugin detects, validates,
and reports what is missing — the pattern `scripts/detect_profile.py` already uses for
test gates, extended rather than invented.

That file is also the missing declaration between the two workflow spines, and it is
checkable in CI.

### 4 · Two preconditions block the work

- **Collapse the note-vault triple** — `cms`, the local library's `ctxmem.js`, and the
  game repo's `ctx-verify.mjs`/`ctx-index.mjs` are three implementations of one idea.
  `cms` becomes the owner first, or the marketplace maintains four.
- **Extend `scripts/check-public-safe.sh` and close the game repo's open
  externalise-the-Photon-app-id item.** The material carries a hardcoded key, teammate
  names and addresses, and chat-webhook setup. Publication is irreversible.

### 5 · What is explicitly rejected

- **A Unity knowledge plugin.** The shelf is full, the content rots on the engine's
  release cadence, and this project already discarded its own.
- **A separate harness plugin.** An earlier draft proposed one; `act-for-real` already
  holds the thesis. One box, not two.
- **Folding the whole local library into hephaestus.** Employer-adjacent skills cannot
  go public under the secret-guard rule. Two homes remain — split by an enforceable
  rule instead of by accident.

## Status

Accepted — implemented 2026-08-16 on `feature/adr-003-plugin-decomposition`.

## Consequences

**Easier.** `finish-branch` becomes meaningful in a repository with no test suite, which
is the current defect. Domain tooling gains a stated home and a stated boundary, so the
next domain question is a lookup rather than a re-litigation. The verification discipline
reaches every repo that installs `crucible`, not only game repos. A second engine becomes
an adapter rather than a rewrite.

**Harder.** `forge-unity` will be under constant pull toward knowledge content, because
knowledge is the cheapest thing to write and the most visibly useful in a demo; resisting
it is a standing cost. The adapter contract adds a file every consuming project must
maintain, and a stale mapping fails in the class of way this ADR exists to prevent — so
`/forge-init` must validate, not merely scaffold. Publishing extracted material widens the
public-safe surface permanently.

**Follow-up implied.**

1. Collapse the vault triple into `cms`; the game repo's tools become thin calls.
2. Extend `check-public-safe.sh`; close the Photon app-id item.
3. Ship the four `crucible` additions, each with a behavioral eval scenario — a new
   falsifiable claim requires one.
4. Ship `forge-unity` plus `.forge/adapter.json`. **Done means the game repo's local
   skills are deleted, not kept alongside**; if both persist, the seam did not work.
5. Add cross-plugin duplication scoring (pairwise description similarity, duplicated
   passages) to the skill-quality gate — the check that would have surfaced the vault
   triple mechanically instead of by manual reading.
6. Declare the crucible ↔ project seam in the consuming repo's `CLAUDE.md`.

**Resolved 2026-08-16 — the standalone-Player question.** This was recorded as unverified
because three documentation sources could not answer it (the vendor blog returned 403, the
package overview is a pre-release stub, the community server's catalogue is not enumerated
in its README). Settled instead by reading the source tree of `CoplayDev/unity-mcp` through
the GitHub API:

| Capability | Off-the-shelf MCP | Where |
|---|---|---|
| Enter/exit Play Mode | **yes** | `ManageEditor.cs`, `case "play"` → `EditorApplication.isPlaying` |
| Read console | **yes** | `ReadConsole.cs` |
| Recompile / refresh | **yes** | `RefreshUnity.cs` |
| Run tests, build | **yes** | `RunTests.cs`, `ManageBuild.cs` |
| Screenshot | **yes** | `ScreenshotUtility.cs` (`ScreenCapture`, camera → `RenderTexture`) |
| **Drive a standalone development Player** | **no** | — |

Every tool lives under `MCPForUnity/Editor/`, and `EditorApplication.isPlaying` is an Editor
API by construction. The `Runtime/` assembly exists — but it contains only helpers, compat
shims and serialisation converters, with **no server, socket or command dispatcher**. It is
there so Editor code can call screenshot and compatibility helpers that also compile into a
player, not so a player can be driven.

Two consequences, and they point in opposite directions, which is why the answer was worth
having:

- **The adapter contract is more justified, not less.** `session.start` and `capture.sheet`
  against a second, standalone peer cannot be served by any off-the-shelf MCP, and a
  two-peer traced run is exactly the evidence class that most needs producing.
- **`forge-unity` should not grow an editor client.** `editor.ping`, `editor.compile` and
  `editor.logs` are all served well by an existing MCP, so a project should map those verbs
  straight to it. That the same contract accommodates both a vendor MCP and a project's own
  transport is the design working as intended — the adapter is transport-agnostic, and this
  is its first outside confirmation.

The token argument survives either way: a registered MCP server costs its full schema on
every request, while a skill costs roughly 100 tokens until invoked.
