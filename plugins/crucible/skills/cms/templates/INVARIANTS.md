# Invariants

Standing constraints for this repository. These hold for **all** work here, not for one
task — that is what separates them from a plan or a spec.

A plan describes what to build and stops mattering once it is built. An invariant is a rule
about how anything gets built, and it has to still be in force on the day someone has
forgotten it exists. Those two things want opposite lifecycles, so they live in different
files. Putting a standing constraint in a task document is why standing constraints get
lost: the document is finished, so the constraint is treated as finished too.

This file deliberately carries **no `last_reviewed_on` / `review_in`**. Those fields ask "is
this still accurate?" on a timer, which is right for a description of the system and wrong
for a rule about it. A constraint does not expire because nobody looked at it. Retiring one
is a decision someone makes and writes down — never a timeout.

## How an entry matures

`PROSE` → `FALSIFIABLE` → `CHECK` → `ENFORCED`

Stating it is step one, and on its own it is the weakest form: a constraint that lives only
as a sentence competes for attention with everything written since, and loses. The work is
turning it into something that fails loudly without anyone remembering it.

- **Falsifiable** — rewrite it so a machine could disagree. `WHEN <trigger> THE SYSTEM SHALL
  <behaviour>`, or Given/When/Then. "Mobile-first" is a value; "at 375px width, no horizontal
  scroll" is a claim that can be wrong.
- **Check** — the falsifiable form, executed. A test, a lint rule, a script.
- **Enforced** — the workflow runs it every milestone, so nobody has to remember it.

`cms check` warns (never errors) about an active invariant with no `Check:`. It is a nudge
toward wiring it up, not a gate — a gate on an unwired *intent* would just teach people to
stop writing intents down.

## Entries

## {{EXAMPLE_TITLE}}

Status: active
Statement: {{ONE_LINE_RULE}}
Falsifiable: WHEN {{TRIGGER}} THE SYSTEM SHALL {{REQUIRED_BEHAVIOUR}}
Check: none yet

<!--
Copy the block above per invariant. Fields:

  Status:      active | retired   (retired entries are kept — the reasoning stays useful,
                                   and deleting one loses why it was ever needed)
  Statement:   one line, in plain language
  Falsifiable: the same rule in a form a machine could disagree with
  Check:       a path to an executable check, relative to the repo root, or `none yet`

A worked example:

  ## No new runtime dependencies without a decision record
  Status: active
  Statement: Adding a runtime dependency needs an ADR first.
  Falsifiable: WHEN the dependency manifest gains an entry THE SYSTEM SHALL require a
    matching ADR in docs/decisions/.
  Check: scripts/checks/deps_have_adr.py

The check lives in this repository, not in the tooling — what counts as a violation is a
local judgement, and a generic plugin has no business deciding it for you.
-->
