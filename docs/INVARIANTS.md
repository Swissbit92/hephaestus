# Invariants

Standing constraints for this repository. These bind **all** work here, not one task — that
is what separates them from a plan or a spec. A plan stops mattering once it is built; an
invariant has to still be in force on the day someone has forgotten it exists.

No `last_reviewed_on` / `review_in` here, deliberately: those ask "is this still accurate?"
on a timer, which is right for a description of the system and wrong for a rule about it. A
constraint does not expire because nobody looked at it. Retirement is a decision someone
writes down.

Pipeline: `PROSE` → `FALSIFIABLE` → `CHECK` → `ENFORCED`. Conversion guide:
[../plugins/crucible/skills/cms/references/invariants.md](../plugins/crucible/skills/cms/references/invariants.md).

## Generic plugins stay domain-free

Status: active
Statement: A generic plugin must be usable by anyone; it may not carry tokens specific to one
operator's stack.
Falsifiable: WHEN any text file under a generic plugin contains a known domain token THE
SYSTEM SHALL fail the seam check.
Check: scripts/checks/seam_is_clean.sh

## A check that could not run is never reported as a pass

Status: active
Statement: Every gate distinguishes "passed" from "could not determine", and the latter never
reads as success.
Falsifiable: WHEN a Phase 4.0 script cannot complete its check THE SYSTEM SHALL exit with a
code distinct from success.
Check: none yet
