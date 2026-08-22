# Retrieval: why summaries, and what a good one looks like

Loaded on demand. The rules that bind every edit live in `SKILL.md`; this is the reasoning
behind them and the worked guidance for writing a summary.

## The bill this is paying

The `@path`-versus-plain-link rule controls what is loaded **unconditionally**. This
controls what is loaded **while you are still looking** — the other half of the same bill,
and the half that grows with the corpus rather than with the answer.

Searching by opening candidates costs the full text of everything you opened and were
wrong about. At ten documents that is free. At fifty, finding one page costs most of a
context window, and the cost is paid again on every session that has to look. So documents
declare an optional `ai_summary` in frontmatter and `triage.py` prints them as a routing
table: read the table, pick one document, open that one.

Note what the table is *not*. It is not a search index and it is not a substitute for the
documents. It is a cheap discriminator whose only job is to make the expensive read
correct on the first try.

## Why each rule is the way it is

**A summary says what the document is and when to open it — never what is in it.**
A summary of the contents is a second copy of the document. It goes stale on its own
schedule, and a stale summary is worse than no summary, because it is trusted. Writing
"when to open it" also fails safe: if the document changes and the *reason to open it* has
not, the summary is still true.

**It is bounded** (`AI_SUMMARY_MAX_BYTES`, 1500 — about a short paragraph). It is re-read
on every triage pass, so an unbounded summary is charged again and again for content
nobody asked for. Past the cap it costs more than opening the body it was meant to save
you from opening, which is the exact failure it exists to prevent. `check` raises a
Warning, not an Error: the document is still valid, it has merely stopped earning its
place in the index.

**It is optional, and documents without one are listed anyway**, marked and sorted last.
An index that silently omitted them would route confidently *around* the part of the
corpus it cannot see, which is the most expensive failure available here — you do not
know you missed anything. Optional is also deliberate: requiring it would invalidate every
document already on this schema, and a summary written to satisfy a linter is worse than
none.

**Re-derive the summary whenever the body changes materially.** A summary describing the
previous version is not a small error; it is a confident wrong answer at the exact moment
someone is deciding what to read.

## Writing one

A usable summary answers three questions in this order:

1. **What is this document?** ("Settles how hephaestus takes on domain-specific tooling…")
2. **What does it decide or contain that nothing else does?** — the discriminator. This is
   the part that makes the table worth reading rather than a list of titles.
3. **When should someone open it?** ("Read it before adding any domain plugin…")

Anti-patterns, each seen in the wild:

| Anti-pattern | Why it fails |
|---|---|
| Restating the title | Adds a line to the table and no discrimination |
| Summarising the contents section by section | A second copy, staling independently |
| "Various notes on X" | Cannot discriminate against any other document about X |
| Writing to fill the 1500 bytes | The cap is a ceiling, not a target |

## The aggregate is the thing actually charged

The per-document cap bounds one row. What a triage pass pays is the **sum of every row**,
and that grows with the corpus while each individual summary stays comfortably legal.
Fifty documents at the cap is a routing table costing more than the reads it was meant to
replace — every summary passing its check, and the mechanism defeated anyway.

`check` therefore also reports the aggregate against `AI_SUMMARY_AGGREGATE_WARN_BYTES`.
When it fires, the fix is almost never to trim every summary by a few bytes: it is that
the corpus has outgrown a flat table and wants splitting by directory, or that documents
which should have been archived are still being indexed.
