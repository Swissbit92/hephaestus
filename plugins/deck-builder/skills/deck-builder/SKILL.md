---
name: deck-builder
description: Build a polished .pptx slide deck from source material (a doc, notes, an outline, figures). Use when the user asks to make slides, a deck, a presentation, or a PowerPoint. Code-backed — the model calls named layout methods in deck_lib.py, never hand-rolls slide geometry. Requires an outline-approval gate before building.
---

You turn source material into a clean, on-brand `.pptx` — by composing **named layout
methods** from `deck_lib.py`, never by hand-rolling shapes and coordinates. Your judgement
goes into the narrative and the per-slide assertions; the library handles geometry, brand,
footer, and page numbers.

## Phase 1 — Gather & outline

Read the source (doc/notes/figures). Draft a JSON outline: an ordered list of slides, each
`{layout, headline, body|tiles, notes}`. Apply `design-rules.md`:
- Every content headline is a **full declarative sentence stating the takeaway** ("Manual
  joins make batch genealogy brittle"), not a topic label ("Current challenges").
- Arc: SCQA (situation → complication → question → answer). One idea per slide.

## Phase 2 — Approve the outline (HARD GATE)

Present the outline and **stop**. Do not build until the user signs off. This is the cheap
place to fix narrative problems — never skip it.

## Phase 3 — Assemble assets

If figures are needed, collect them as image files. When placing images, use
`deck_lib.image_fit(...)` to scale within a box preserving aspect ratio (never force width
AND height — it distorts on Google Slides import).

## Phase 4 — Build

Write a short generator script that imports `deck_lib` and calls named methods per the
approved outline — see `example.py`. Run it to produce the `.pptx`. Do **not** emit raw
python-pptx geometry; if a layout you need is missing, add a method to `deck_lib.py` rather
than inlining coordinates.

```bash
python3 your_generator.py   # imports deck_lib; requires: pip install python-pptx
```

## Phase 5 — Review

Open/inspect the result. Check: headlines are assertions, one idea per slide, images
undistorted, footer/page numbers present, speaker notes are a talk track (not a reprint).

## Output

A `.pptx` at the path the user wants, plus a one-line summary of slide count and structure.

## Guardrails

- **Outline approval is mandatory** (Phase 2) — never build unapproved.
- **Never hand-roll geometry** — call `deck_lib` methods; extend the library if needed.
- **Preserve aspect ratio** for every image (`image_fit`).
- **Brand lives in `PALETTE`** — change colors there or via `Deck(palette=...)`, not inline.
