# The BLOCKED signal — when the environment is lying, stop rather than retry

Some environment states let a system **accept a call, report success, and do nothing**. The
agent is not wrong about any single step; it is operating on a belief about the world that
the world stopped sharing. Retrying is the natural response and the wrong one: it burns
turns, and it produces *contradictory* evidence — some calls landed somewhere, some did
not, and afterwards nothing in the transcript can be trusted to mean what it says.

This is the same separation `act-for-real` step 6 gates on, at session scale rather than at
action scale: **the channel that reports and the channel that acts are not the same
channel.**

## Worked examples of "succeeded and did nothing"

Every one of these has cost a real session somewhere:

| Symptom | Actual cause |
|---|---|
| Writes report success; files never change; new files get no metadata | A second, read-only instance of the tool is bound to the same port and calls route between them at random |
| Behaviour flips between identical calls | Two processes serving one endpoint |
| Calls time out, but the port **is** listening | A modal dialog froze the main thread — the OS keeps the socket open regardless, so a port check reports health |
| A build request is refused while everything else answers | The tool refuses that one operation in its current mode |
| A file is written to a path that exists on one platform | Surfaces much later as an unrelated-looking lookup failure |

The last two matter most, because they are *partial*: most of the environment is fine, so
every heuristic says "healthy".

## The rule

**Detect with a script; never diagnose by hand.** A human-eyeball diagnosis of this class of
problem is itself unreliable — the evidence is contradictory by definition. A detector that
exits `0` clear / non-zero blocked, and whose output *names the fix*, is what turns a
confusing session into one line.

**When blocked, say so as the first line of the reply, verbatim:**

```
🛑 BLOCKED — <one-line cause>
   DO: <single concrete action for the user>
   (nothing else can proceed until this clears)
```

First line, not buried mid-message. Then **stop all work that depends on that environment**
and continue only with what does not.

Three properties make the format worth following exactly:

- **One cause, one action.** A list of possibilities is a diagnosis the reader has to
  finish. If you cannot name one action, you have not detected the block, you have noticed
  a symptom.
- **It is not a failure report.** Nothing is broken in the work; the environment cannot be
  reached. Those get different responses from the human, so they must look different.
- **It ends the turn's ambition, not the turn.** Work that does not touch the blocked system
  continues, and saying so is what stops the session becoming a standoff.

## Its relationship to `could-not-check`

They are the same fact at two altitudes, and they should agree:

- **BLOCKED** is the live signal, mid-session: *I cannot reach the thing right now.*
- **`could-not-check`** is the recorded verdict, at the gate: *this class of evidence was
  never produced here.*

A session that emitted BLOCKED and then recorded `pass` has contradicted itself. If the
block prevented an evidence class, the verdict is `could-not-check` and the gap gets named —
see `finish-branch` Phase 1.

## What this is not

Not a retry policy, and not an error handler. An error you can read is a normal failure:
report it and act on it. This is for the case where **the report itself is unreliable**, and
the only correct move is to stop generating more of them.
