---
name: unity-bridge
description: Drive a Unity project's own editor and runtime commands through an engine-neutral vocabulary declared in .forge/adapter.json, so a workflow can ask for a compile gate, a run, tick-exact input, a trace or a contact sheet without naming any one project's commands. Use when a change needs evidence that it actually ran, when an editor call reports success but nothing changed, or when deciding whether an evidence class can be produced on this machine at all. Reports a gap rather than inventing a command name.
metadata:
  depends_on: [unity-asset-integrity]
---

You produce **evidence that something ran** — the thing `crucible:finish-branch` asks for
and a compiler cannot supply. You never invent a command name, and you never treat a
returned success as proof.

## The one rule

**A call can succeed and do nothing.** The channel that reports and the channel that acts
are separate: an editor can accept a request, answer `success: true`, and change nothing —
because a second instance is bound to the same port, because the asset database is in a
read-only mode, because a modal dialog has frozen the main thread while the socket stays
open. None of these produce an error.

So **assert on state read back afterwards** — a file on disk, a status call, an image, a
trace row. Never on the return value. When the environment itself is the unreliable part,
stop rather than retry: retrying produces contradictory evidence, and afterwards nothing in
the session can be trusted. The signal and the detector rule are
`crucible:act-for-real`'s `references/blocked-signal.md`.

## The vocabulary, and why it is not Unity's

Skills are written against canonical verbs; a project maps them to its own commands in
`.forge/adapter.json`. That is what makes the workflow portable — a Godot or Unreal adapter
is a config file rather than a rewrite.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/adapter.py" --vocabulary        # the canonical set
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/adapter.py" --repo . --list     # what this project has
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/adapter.py" --repo . --resolve capture.sheet
```

`0` resolved · `2` the declaration is present and malformed (**fix it, never delete it**) ·
`3` no declaration, or **this project does not implement that verb**.

**Exit 3 is the important one.** It means the evidence cannot be produced here, which maps
to `could-not-check` at the gate — not to a failure, and never to a pass. The one thing you
must not do is guess a plausible command name: a well-formed guess runs nothing and is
reported as success, which is the exact failure this whole plugin exists to prevent.

Run `/forge-init` to scaffold the declaration.

### Map the editor verbs to an existing MCP; the player verbs have no vendor

Verified against `CoplayDev/unity-mcp`'s source on 2026-08-16, and it splits cleanly:

- **`editor.ping` / `editor.compile` / `editor.logs` are solved.** An off-the-shelf Unity
  MCP serves them, along with play mode, tests, builds and screenshots. Map those verbs
  straight to it rather than writing a client — this plugin deliberately does not ship one.
- **Nothing off the shelf reaches a standalone development Player.** Every tool in that
  server lives under an `Editor/` assembly, and its `Runtime/` assembly holds only helpers
  and compat shims — no server, no socket, no dispatcher. So `session.start`,
  `input.script`, `trace.dump` and `capture.sheet` **against a second peer** are yours to
  implement, which is precisely why the mapping exists.

That split is the contract earning its keep: one declaration accommodates a vendor MCP and
a project's own transport at the same time.

## Producing evidence, in the order that makes it cheap

1. **Gate the compile first.** `editor.compile` exits non-zero on error, so it is usable
   directly as a gate. Everything below is wasted if this fails, and it is the cheapest
   check you have.
2. **A new source file is not a compiled source file.** Requesting a compile does not
   *import* anything. A file the editor has never imported reports as a missing-type error
   that looks like a real compile failure and is not — refresh assets, then compile again,
   before believing the message. `unity-asset-integrity` detects the same condition
   statically, without a running editor.
3. **Start the run, then ask whether it started.** `session.start` is asynchronous
   essentially everywhere; the call returning is not the session existing.
   `session.status` is the answer.
4. **Drive input through `input.script`, not by hand.** A run nobody can repeat is an
   anecdote. Tick-exact input is what makes the same run reproducible against a fix.
5. **Read `trace.transitions` before `trace.dump`.** Transitions are the cheap view; take
   the full dump only when the question is genuinely about a curve.
6. **`capture.sheet` for anything visual**, and capture it **on the peer that is supposed
   to see it**. A host-side image proves nothing about what a client renders — that is the
   most common way a visual change passes a gate it should have failed.

## Two things that will cost you a session

- **Never write an unbounded wait loop** (`until ping; do sleep 2; done`). Against a frozen
  editor it spins forever and produces no signal at all — which is precisely the failure it
  looks like it is guarding against. Make one call with a generous timeout and branch on
  the exit code.
- **Comparing raw step numbers across two peers is meaningless.** A client predicts ahead,
  so the same event carries a different number on each. Compare the *offsets between*
  events, which agree.

## Verification

- Every claim traces to something read back: a path, a status, an image, a trace row.
- A verb that is not implemented was **reported**, with the class it blocks named — never
  substituted with a guess.
- Anything visual was captured on the peer that should see it.
