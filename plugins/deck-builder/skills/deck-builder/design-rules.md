# Deck design rules (generic, research-backed)

Actionable constraints the deck-builder skill applies. Sources noted for rationale, not
citation theater.

## Narrative
- **Assertion-evidence (Alley).** Every content slide's headline is a full declarative
  sentence stating the takeaway — "Batch genealogy requires brittle manual SQL joins", not
  "Current challenges". The body is the evidence for that assertion.
- **SCQA (Minto).** Structure the arc: Situation → Complication → Question → Answer. Lead
  with why the audience should care.
- **One idea per slide.** If a slide needs two headlines, it's two slides.

## Visual
- **Data-ink (Tufte).** Maximize the ratio of information to decoration. No chartjunk, no
  gratuitous gradients, no clip art.
- **Cognitive load (Mayer/Sweller).** Short bullets (or none — prefer a sentence + a
  visual). Don't read the slide to the audience; that's what speaker notes are for.
- **Aspect ratio.** Never distort images — scale to fit a box (`image_fit`). 16:9 canvas.
- **Contrast & hierarchy.** One accent color for emphasis; consistent type scale (the
  library enforces this).

## Speaker notes
- Notes are the **talk track**, not a reprint of the slide. Write what you'd *say*.

## Anti-patterns
- Topic-label headlines ("Overview", "Results").
- Walls of text / 8-bullet slides.
- Hand-tuned per-slide geometry (use named layouts; extend the library instead).
- Inventing data — every number on a slide must trace to the source material.
