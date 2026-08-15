#!/usr/bin/env python3
"""Compute a note vault's link graph and health facts — deterministically.

The `review` action asks four questions that are pure counting: what links to nothing,
what nothing links to, which links point at notes that do not exist, and which tags look
like variants of each other. Answering those by reading every note costs tokens
proportional to the vault, cannot be unit-tested, and gives a slightly different answer
each run — so a vault cannot be trended over time, which is the only reason to run a
health report more than once.

This does the counting. The model keeps the part that needs judgment, and the split is
drawn where a script genuinely stops being able to help: the near-duplicate tag check
finds case, separator, plural and typo variants, because those are string facts. It does
NOT find semantic aliases — `#ml` and `#machine-learning` share no substring, and no
string metric will ever pair them. Those are reported as a shortlist for the model to
judge, never silently merged.

Read-only. Never writes to the vault.

Exit codes:
    0 — the report was produced (findings are information, not failure)
    2 — could not determine: the vault path is missing or unreadable. NOT a pass.
    1 — unused. A health report has no "regression" verdict to give; the caller decides
        what an orphan count means, so overloading 1 would invent a policy here.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import time
from pathlib import Path

# Notes untouched for longer than this are listed, never modified.
DEFAULT_STALE_DAYS = 180

# Two tags whose normalised forms are at least this similar are offered as possible
# duplicates. Tuned to catch typos and inflections without pairing every short tag with
# every other one.
TAG_SIMILARITY = 0.85

# Directories that are never notes.
SKIP_DIRS = {".obsidian", ".git", ".trash", "node_modules", "__pycache__"}

# The controlled vocabulary is a declaration, not a note. Counting it as one makes it a
# permanent orphan (nothing links to a tag list) and turns every *declared* tag into a
# use, so a vocabulary listing ten approved tags reports ten tags "used once" — burying
# the real singletons the section exists to surface.
VOCAB_REL = "_meta/tags.md"

# `[[Target]]`, `[[Target|Alias]]`, `[[Target#Heading]]`, `[[Target#^block]]` and the
# `![[embed]]` form. The target is everything before the first | or #.
WIKILINK_RE = re.compile(r"!?\[\[([^\]\[|#]+)(?:[#|][^\]]*)?\]\]")

# A tag is # followed by a letter — `#1` is a number, and `# Heading` is a heading.
# Obsidian allows nesting (`#a/b`), hyphens and underscores.
TAG_RE = re.compile(r"(?:^|(?<=\s))#([A-Za-z][A-Za-z0-9_/-]*)")

# Fenced blocks and inline code: a `[[link]]` inside them is an example, not a link.
FENCE_RE = re.compile(r"^```.*?^```", re.M | re.S)
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")


def _utf8_stdio() -> None:
    """Force UTF-8 on the streams this script writes to.

    Windows consoles default to a legacy codepage (commonly cp1252), so a single em-dash
    or check-mark in otherwise successful output raises UnicodeEncodeError *after* the
    work is done — turning a passing gate into exit 1, which reads as a real failure.
    Reconfiguring is a no-op on platforms that are already UTF-8.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass  # a detached or captured stream (pytest); nothing to reconfigure


def strip_code(text: str) -> str:
    """Remove fenced and inline code so examples are not mistaken for real links/tags."""
    return INLINE_CODE_RE.sub(" ", FENCE_RE.sub(" ", text))


def split_frontmatter(text: str) -> tuple[str, str]:
    """(frontmatter, body). Frontmatter tags count; frontmatter is not scanned for links."""
    if not text.startswith("---"):
        return "", text
    end = re.search(r"^---\s*$", text[3:], re.M)
    if not end:
        return "", text
    return text[3:3 + end.start()], text[3 + end.end():]


def frontmatter_tags(fm: str) -> set[str]:
    """Tags declared in frontmatter, in either the inline-list or block-list form."""
    tags: set[str] = set()
    # [ \t]* rather than \s*: \s matches newlines, so on the block-list form the pattern
    # would swallow the line break and capture the first "- gamma" bullet as if it were
    # an inline value.
    m = re.search(r"^tags:[ \t]*(.*)$", fm, re.M)
    if not m:
        return tags
    inline = m.group(1).strip()
    if inline:
        tags |= {t.strip().strip("'\"#") for t in inline.strip("[]").split(",") if t.strip()}
    # block form: subsequent "  - value" lines
    for line in fm[m.end():].splitlines():
        if re.match(r"^\s*-\s+", line):
            tags.add(line.split("-", 1)[1].strip().strip("'\"#"))
        elif line.strip() and not line.startswith((" ", "\t")):
            break
    return {t for t in tags if t}


def find_notes(vault: Path) -> list[Path]:
    return sorted(p for p in vault.rglob("*.md")
                  if not any(part in SKIP_DIRS for part in p.relative_to(vault).parts)
                  and p.relative_to(vault).as_posix() != VOCAB_REL)


def scan(vault: Path, stale_days: int = DEFAULT_STALE_DAYS, now: float | None = None) -> dict:
    """Parse every note once and derive the graph. One pass, no re-reads."""
    now = time.time() if now is None else now
    notes: dict[str, dict] = {}
    # Obsidian resolves a link by note name, not by path, so index both.
    by_stem: dict[str, list[str]] = {}

    for path in find_notes(vault):
        rel = path.relative_to(vault).as_posix()
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        fm, body = split_frontmatter(raw)
        clean = strip_code(body)
        links = [m.group(1).strip() for m in WIKILINK_RE.finditer(clean)]
        tags = {t.lower() for t in TAG_RE.findall(clean)} | {t.lower() for t in frontmatter_tags(fm)}
        try:
            age_days = int((now - path.stat().st_mtime) / 86400)
        except OSError:
            age_days = 0
        notes[rel] = {"path": rel, "stem": path.stem, "links": links,
                      "tags": sorted(tags), "age_days": age_days,
                      "inbound": [], "broken": []}
        by_stem.setdefault(path.stem.lower(), []).append(rel)

    # Resolve links the way Obsidian does: an exact path first (with or without the .md
    # suffix), then the bare note name. Indexed rather than searched — a linear scan per
    # link makes a big vault quadratic, which is exactly the cost this script exists to
    # remove.
    by_path = {rel.lower(): rel for rel in notes}
    for rel, note in notes.items():
        for target in note["links"]:
            key = target.lower().removesuffix(".md")
            dest = by_path.get(f"{key}.md") or by_path.get(key)
            if dest is None:
                matches = by_stem.get(key.rsplit("/", 1)[-1], [])
                dest = matches[0] if matches else None
            if dest is None:
                note["broken"].append(target)
            elif dest != rel:
                notes[dest]["inbound"].append(rel)

    orphans = sorted(r for r, n in notes.items()
                     if not n["inbound"] and not [l for l in n["links"] if l])
    stale = sorted(((n["age_days"], r) for r, n in notes.items() if n["age_days"] > stale_days),
                   reverse=True)
    broken = sorted((r, t) for r, n in notes.items() for t in n["broken"])

    tag_counts: dict[str, int] = {}
    for n in notes.values():
        for t in n["tags"]:
            tag_counts[t] = tag_counts.get(t, 0) + 1

    return {
        "vault": vault.as_posix(),
        "note_count": len(notes),
        "notes": notes,
        "orphans": orphans,
        "stale": [{"path": r, "age_days": d} for d, r in stale],
        "stale_days": stale_days,
        "broken_links": [{"from": r, "target": t} for r, t in broken],
        "tags": dict(sorted(tag_counts.items())),
        "tag_singletons": sorted(t for t, c in tag_counts.items() if c == 1),
        "tag_variants": tag_variants(tag_counts),
        "uncontrolled_tags": uncontrolled(vault, tag_counts),
    }


def _normalise_tag(tag: str) -> str:
    """Fold the differences that are spelling rather than meaning."""
    t = re.sub(r"[-_/]", "", tag.lower())
    return t[:-1] if t.endswith("s") and len(t) > 3 else t


def tag_variants(tag_counts: dict[str, int]) -> list[dict]:
    """Tag pairs that differ only in spelling — case, separators, plural, or a typo.

    Semantic aliases are out of reach here by construction and are left to the model:
    `#ml` and `#machine-learning` have no string relationship to find.
    """
    tags = sorted(tag_counts)
    out: list[dict] = []
    for i, a in enumerate(tags):
        for b in tags[i + 1:]:
            na, nb = _normalise_tag(a), _normalise_tag(b)
            if na == nb:
                reason = "same after folding case/separators/plural"
            elif difflib.SequenceMatcher(None, na, nb).ratio() >= TAG_SIMILARITY:
                reason = "near-identical spelling"
            else:
                continue
            out.append({"a": a, "b": b, "counts": [tag_counts[a], tag_counts[b]],
                        "reason": reason})
    return out


def uncontrolled(vault: Path, tag_counts: dict[str, int]) -> list[str]:
    """Tags absent from the controlled vocabulary. Empty when the vault declares none —
    a vault without `_meta/tags.md` has not opted into a vocabulary, and inventing one
    would report every tag as a violation."""
    vocab_file = vault / VOCAB_REL
    if not vocab_file.is_file():
        return []
    try:
        text = vocab_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    vocab = {t.lower() for t in TAG_RE.findall(text)}
    vocab |= {m.group(1).strip().lower() for m in re.finditer(r"^\s*[-*]\s+`?#?([A-Za-z][\w/-]*)`?", text, re.M)}
    return sorted(t for t in tag_counts if t not in vocab)


def render(data: dict, top: int) -> str:
    """Compact report, worst offenders first."""
    lines = [f"VAULT  {data['vault']}  ·  {data['note_count']} notes", ""]

    def section(title: str, rows: list[str], total: int) -> None:
        lines.append(f"{title} ({total})")
        if rows:
            lines.extend(f"  {r}" for r in rows[:top])
        else:
            lines.append("  none")
        if total > top:
            lines.append(f"  … {total - top} more")
        lines.append("")

    section("ORPHANS — no inbound and no outbound links",
            data["orphans"], len(data["orphans"]))
    section("BROKEN LINKS — target does not resolve",
            [f"{b['from']}  ->  [[{b['target']}]]" for b in data["broken_links"]],
            len(data["broken_links"]))
    section(f"STALE — untouched > {data['stale_days']} days",
            [f"{s['age_days']:>5}d  {s['path']}" for s in data["stale"]], len(data["stale"]))
    section("TAG VARIANTS — spelling, not meaning",
            [f"#{v['a']} ({v['counts'][0]})  ~  #{v['b']} ({v['counts'][1]})  — {v['reason']}"
             for v in data["tag_variants"]], len(data["tag_variants"]))
    section("TAGS USED ONCE — fold in or keep deliberately",
            [f"#{t}" for t in data["tag_singletons"]], len(data["tag_singletons"]))
    if data["uncontrolled_tags"]:
        section("NOT IN _meta/tags.md",
                [f"#{t}" for t in data["uncontrolled_tags"]], len(data["uncontrolled_tags"]))

    lines.append("Semantic aliases (#ml vs #machine-learning) are not detectable from "
                 "spelling and are deliberately not reported — that judgement is the "
                 "model's, from the tag list above.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("vault", nargs="?", default=".", help="vault root (default: cwd)")
    ap.add_argument("--stale-days", type=int, default=DEFAULT_STALE_DAYS,
                    help=f"age at which a note is listed as stale (default: {DEFAULT_STALE_DAYS})")
    ap.add_argument("--top", type=int, default=10, help="rows per section (default: 10)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    a = ap.parse_args(argv)

    vault = Path(a.vault)
    if not vault.is_dir():
        print(f"cannot determine: {vault} is not a directory", file=sys.stderr)
        return 2

    data = scan(vault, a.stale_days)
    if not data["note_count"]:
        print(f"cannot determine: no .md notes under {vault}", file=sys.stderr)
        return 2

    if a.json:
        # `notes` carries every note's full link list; useful programmatically, far too
        # verbose for a report, so it is dropped unless explicitly wanted.
        payload = {k: v for k, v in data.items() if k != "notes"}
        print(json.dumps(payload, indent=2))
    else:
        print(render(data, a.top))
    return 0


if __name__ == "__main__":
    _utf8_stdio()
    raise SystemExit(main())
