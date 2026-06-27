# second-brain

An Obsidian (or any Markdown) **inbox processor** for Claude Code. It reads your captured
notes and *proposes* tags, links, filing, and action items — then applies only what you
approve, one note at a time. It never edits your vault on its own.

## Why propose-only

Two failure modes kill a note vault: auto-capture without review (a note graveyard), and
autonomous tagging/linking that invents *false* connections ("matching words, not
meaning"). This skill is deliberately the opposite — **you are the only committer**. Its job
is good suggestions plus the restraint to skip when unsure.

## What it does

- Reads your inbox (default `Inbox/`) and your controlled tag vocabulary first.
- For each note, proposes a fixed, auditable block: summary, kind, tags (with reasons),
  links (only real conceptual matches), extracted actions, and a filing destination.
- Applies per-item on your explicit approval; **merges** by appending a dated section rather
  than overwriting; never invents tags or links on surface word overlap.

## Install

```
/plugin marketplace add Swissbit92/whetstone
/plugin install second-brain@whetstone
/second-brain        # point it at your vault's inbox
```

It's also model-invoked: Claude triggers it when you ask to process/triage your notes
inbox or "run my second brain."

## Guardrails (the short version)

Never auto-applies · vocabulary-first tags (new ones capped + flagged) · links only on real
conceptual match · append-dated-section merges (no destructive rewrites) · no pipelines or
external syncs.

## License

MIT.
