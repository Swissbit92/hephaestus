---
title: Architecture
status: active
created: 2026-06-28
last_reviewed_on: 2026-06-28
review_in: 6 months
applies_to: hephaestus
---

# Architecture

Reference-style: tables and diagrams, not prose narratives.

## System context

```
[External input] → hephaestus → [Output / downstream consumer]
```

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

Link any shared/canonical contracts this repo depends on (plain links, never `@path`).

hephaestus has none: it is a single repository with no root-level `docs/shared/`, so every
contract it depends on is internal. The scaffolded placeholder that used to sit here pointed
at a file that has never existed — caught by the link check added with ADR-003, which is
exactly the rot that check is for.

## Decisions

Architectural decisions affecting this repo live in [decisions/](decisions/).
