---
title: Architecture
status: active
created: {{TODAY}}
last_reviewed_on: {{TODAY}}
review_in: 6 months
applies_to: {{REPO_NAME}}
---

# Architecture

Reference-style: tables and diagrams, not prose narratives.

## System context

Say in one sentence which question this figure answers, then edit the model and
run `/cms render`. Delete the block entirely if the repo does not warrant a
diagram yet — an empty diagram is worse than none.

```archview
{
  "id": "context",
  "caption": "What this repo is to everything around it.",
  "nodes": [
    {"id": "upstream", "label": "TBD upstream", "kind": "external"},
    {"id": "entry", "label": "{{REPO_NAME}}", "sub": "TBD responsibility", "tech": "TBD", "kind": "service"},
    {"id": "store", "label": "TBD store", "sub": "TBD contents", "tech": "TBD", "kind": "store"},
    {"id": "downstream", "label": "TBD consumer", "sub": "reads, never writes", "kind": "external"}
  ],
  "edges": [
    {"from": "upstream", "to": "entry", "label": "TBD"},
    {"from": "entry", "to": "store", "label": "writes"},
    {"from": "store", "to": "downstream", "label": "TBD"}
  ]
}
```

Once the model above is real, an `archflow` block walks it — same boxes, no second
diagram to keep in step. Delete it if nothing here happens in a sequence worth
tracing. It must stay *below* the view it names.

```archflow
{
  "view": "context",
  "flows": [
    {
      "id": "main-path",
      "label": "TBD — the thing this repo does most often",
      "steps": [
        {"node": "upstream", "note": "TBD — one sentence per step, read aloud on arrival"},
        {"edge": ["upstream", "entry"]},
        {"node": "entry", "note": "TBD"},
        {"edge": ["entry", "store"], "note": "TBD"}
      ]
    }
  ]
}
```

`docs/ARCHITECTURE.html` is **generated** from this file by `/cms render` and must
never be hand-edited. Schema, the view catalogue and the structural check:
`references/architecture-views.md` in the cms skill.

## Components

| Component | Responsibility | Module |
|-----------|----------------|--------|
| TBD       | TBD            | TBD    |

## Data

| Source | Format | Writer | Readers |
|--------|--------|--------|---------|
| TBD    | TBD    | TBD    | TBD     |

## Key invariants

- TBD

## Cross-repo contracts

Link any shared/canonical contracts this repo depends on (plain links, never `@path`):
- [TBD shared contract](../docs/shared/TBD.md)

## Decisions

Architectural decisions affecting this repo live in [decisions/](decisions/).
