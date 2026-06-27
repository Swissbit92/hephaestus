# deck-builder

Build polished `.pptx` decks from source material (a doc, notes, an outline, figures) in
Claude Code. **Code-backed**: the model composes named layout methods from `deck_lib.py` —
it never hand-rolls slide geometry — so decks come out consistent and on-brand.

## How it works

1. **Outline** the deck as structured slides (assertion headlines, SCQA arc).
2. **Approve** the outline — a hard gate; nothing is built until you sign off.
3. **Build** via a short generator script that imports `deck_lib` and calls
   `title_slide` / `content_slide` / `section_divider` / `stat_tiles` / `closing_slide`.
4. **Review** against `design-rules.md`.

## Layout methods (`deck_lib.Deck`)

`title_slide` · `section_divider` · `content_slide` · `stat_tiles` · `closing_slide` ·
`notes` · `save`. Footer + page numbers are applied automatically; images use `image_fit`
to preserve aspect ratio.

## Install & requirements

```
/plugin marketplace add Swissbit92/whetstone
/plugin install deck-builder@whetstone
```

Building a deck needs `python-pptx` (`pip install python-pptx`). The skill's pure helpers
(palette, `image_fit`, text fitting) need nothing — `python-pptx` is imported lazily only
when a `Deck` is actually constructed.

## Make it your brand

Edit `PALETTE` / `FOOTER` in `deck_lib.py`, or pass `Deck(palette={...}, footer="...")`.
See `example.py` for a complete worked deck and `design-rules.md` for the narrative/visual
rules the skill enforces.

## License

MIT.
