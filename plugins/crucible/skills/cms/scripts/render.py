#!/usr/bin/env python3
"""Render docs/ARCHITECTURE.md into docs/ARCHITECTURE.html — a human view of a
file that stays the single source of truth.

THE POINT, because it is easy to lose: this does NOT introduce a second
architecture document. `ARCHITECTURE.md` is authored and CMS-governed exactly as
it is today; the HTML is derived from it and must never be hand-edited. Drift
between the two is structurally impossible rather than merely policed — which is
the only version of this idea worth having, since a second hand-maintained file
would double the staleness surface rather than solve it.

Diagrams come from fenced ```archview blocks inside the markdown, the way mermaid
already lives in markdown. One file to edit, one linter to satisfy.

Bespoke, repo-specific visuals go in a fenced ```html block and pass through
untouched. That is deliberate — "the one thing this repo does" is different in
every repo and cannot be schema'd, so the format offers a socket rather than a
type. A trading service draws its order book; a web app draws its request path.

Pure stdlib, matching the CMS scripts this is intended to join.

    python3 tools/render_arch.py                    # docs/ARCHITECTURE.md -> .html
    python3 tools/render_arch.py --check            # exit 1 if html is stale
    python3 tools/render_arch.py -i X.md -o Y.html
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
from pathlib import Path

# Paths resolve from the repo being rendered, never from this script's own
# location — the script lives in the plugin and the docs do not.
def _default_paths(repo: Path) -> tuple[Path, Path]:
    return repo / "docs" / "ARCHITECTURE.md", repo / "docs" / "ARCHITECTURE.html"

# ── layout constants ────────────────────────────────────────────────────────
# One engine serves both diagram types. A flow and a topology are the same
# problem — a layered DAG — and only their styling differs, so there is one
# layout implementation and two skins rather than two of everything.
PAD_X, PAD_Y = 24, 30
ROW_GAP = 60
COL_GAP = 30
# Height by line count. A node carries up to three lines: what it is called, what
# it does, and what it is built from — the third being C4's convention that
# technology is an annotation on the container, not a separate view.
NODE_H = {1: 40, 2: 54, 3: 66}
CHAR_W = 6.5
MIN_W, MAX_W = 108, 215
GROUP_PAD = 18


# ════════════════════════════════════════════════════════════════════════════
# markdown subset
# ════════════════════════════════════════════════════════════════════════════

def _inline(text: str) -> str:
    """Escape, then re-introduce the few inline forms an architecture doc uses.

    Deliberately small. A full markdown implementation is not the job, and every
    construct supported here is one more thing that can render wrong.
    """
    out = html.escape(text, quote=False)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(?<![*\w])\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", out)
    out = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', out)
    return out


def _table(rows: list[str]) -> str:
    cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
    head, body = cells[0], cells[2:]          # cells[1] is the --- separator
    h = "".join(f"<th>{_inline(c)}</th>" for c in head)
    b = "".join(
        "<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>"
        for r in body
    )
    return (f'<div class="tw"><table><thead><tr>{h}</tr></thead>'
            f"<tbody>{b}</tbody></table></div>")


RE_HEAD = re.compile(r"^(#{1,4})\s+(.*)$")
RE_HR = re.compile(r"^(-{3,}|\*{3,}|_{3,})\s*$")
RE_QUOTE = re.compile(r"^>\s?(.*)$")
RE_OL = re.compile(r"^\s*(\d+)\.\s+(.*)$")
RE_UL = re.compile(r"^\s*[-*]\s+(.*)$")


def _starts_block(line: str) -> bool:
    """Does this line begin a block other than a paragraph?

    Every block form is listed here exactly once, and the paragraph accumulator
    consults this rather than carrying its own copy of the list. The out-of-sample
    run failed precisely because those two lists had drifted: ordered items were
    not recognised AND not treated as terminators, so a numbered pipeline was
    silently swallowed into the paragraph above it.
    """
    return bool(line.startswith(("#", "|", "```"))
                or RE_HR.match(line) or RE_QUOTE.match(line)
                or RE_OL.match(line) or RE_UL.match(line))


def render_markdown(md: str) -> str:
    """Markdown subset -> HTML, with ```archview and ```html handled specially."""
    lines = md.split("\n")
    out: list[str] = []
    i, n = 0, len(lines)

    while i < n:
        line = lines[i]

        if line.startswith("```"):
            lang = line[3:].strip()
            i += 1
            buf: list[str] = []
            while i < n and not lines[i].startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            body = "\n".join(buf)

            if lang == "archview":
                out.append(render_diagram(json.loads(body)))
            elif lang == "html":
                out.append(body)                       # the mechanism socket
            else:
                out.append(f"<pre><code>{html.escape(body)}</code></pre>")
            continue

        # h1 is consumed but not emitted — the page header already shows the repo
        # name, and a second <h1> would just repeat it.
        m = RE_HEAD.match(line)
        if m:
            lvl, txt = len(m.group(1)), m.group(2)
            if lvl > 1:
                slug = re.sub(r"[^a-z0-9]+", "-", re.sub(r"[*`]", "", txt.lower())).strip("-")
                out.append(f'<h{lvl} id="{slug}">{_inline(txt)}</h{lvl}>')
            i += 1
            continue

        if RE_HR.match(line):
            out.append("<hr>")
            i += 1
            continue

        if RE_QUOTE.match(line):
            buf = []
            while i < n and RE_QUOTE.match(lines[i]):
                buf.append(RE_QUOTE.match(lines[i]).group(1))
                i += 1
            # Blank quote lines separate paragraphs inside the quote.
            paras = [" ".join(p.split()) for p in "\n".join(buf).split("\n\n")]
            inner = "".join(f"<p>{_inline(p)}</p>" for p in paras if p.strip())
            out.append(f"<blockquote>{inner}</blockquote>")
            continue

        if RE_OL.match(line):
            items = []
            while i < n and (RE_OL.match(lines[i]) or
                             (items and lines[i].startswith("   ") and lines[i].strip())):
                mo = RE_OL.match(lines[i])
                if mo:
                    items.append(mo.group(2).strip())
                else:
                    items[-1] += " " + lines[i].strip()
                i += 1
            out.append("<ol>" + "".join(f"<li>{_inline(t)}</li>" for t in items) + "</ol>")
            continue

        if line.strip().startswith("|") and i + 1 < n and set(lines[i + 1].strip()) <= set("|-: "):
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append(lines[i])
                i += 1
            out.append(_table(rows))
            continue

        if RE_UL.match(line):
            items = []
            while i < n and (RE_UL.match(lines[i]) or
                             (items and lines[i].startswith("  ") and lines[i].strip())):
                mu = RE_UL.match(lines[i])
                if mu:
                    items.append(mu.group(1).strip())
                else:
                    items[-1] += " " + lines[i].strip()
                i += 1
            out.append("<ul>" + "".join(f"<li>{_inline(t)}</li>" for t in items) + "</ul>")
            continue

        if line.strip():
            start = i
            para = []
            while i < n and lines[i].strip() and not _starts_block(lines[i]):
                para.append(lines[i].strip())
                i += 1
            # Guard, not decoration: if the loop above matched nothing we would
            # emit an empty <p> and never advance — an infinite loop that
            # presents as a hung render with no output. Any branch that can
            # consume zero lines has to force progress.
            if i == start:
                i += 1
                continue
            out.append(f"<p>{_inline(' '.join(para))}</p>")
            continue

        i += 1

    return "\n".join(out)


# ════════════════════════════════════════════════════════════════════════════
# diagram engine — layered DAG
# ════════════════════════════════════════════════════════════════════════════

def _lines(nd: dict) -> int:
    return 1 + bool(nd.get("sub")) + bool(nd.get("tech"))


def _node_w(nd: dict) -> float:
    """Width from the longest line. Tech strings run long, so they get a slightly
    tighter per-character budget rather than forcing every box wider."""
    longest = max(len(nd["label"]),
                  len(nd.get("sub", "")),
                  len(nd.get("tech", "")) * 0.86)
    return max(MIN_W, min(MAX_W, longest * CHAR_W + 24))


def _layer(nodes, edges):
    """Longest-path layering. Back edges are excluded so a cycle cannot hang it —
    they are drawn later as a margin rail, which is also how a reader wants to
    see 'and then it loops'."""
    ids = [nd["id"] for nd in nodes]
    idx = {nid: k for k, nid in enumerate(ids)}
    fwd = [e for e in edges if idx[e["to"]] > idx[e["from"]]]
    back = [e for e in edges if idx[e["to"]] <= idx[e["from"]]]

    layer = {nid: 0 for nid in ids}
    for _ in range(len(ids)):
        changed = False
        for e in fwd:
            if layer[e["to"]] < layer[e["from"]] + 1:
                layer[e["to"]] = layer[e["from"]] + 1
                changed = True
        if not changed:
            break
    return layer, fwd, back


def _place(nodes, layer, groups):
    """Rows top-down, group-contiguous within a row, centred on a common spine."""
    member_of = {}
    for g in groups:
        for mem in g.get("members", []):
            member_of[mem] = g["id"]

    rows: dict[int, list] = {}
    for nd in nodes:
        rows.setdefault(layer[nd["id"]], []).append(nd)

    widths = {}
    for r, row in rows.items():
        row.sort(key=lambda nd: member_of.get(nd["id"], "~"))
        widths[r] = sum(_node_w(nd) for nd in row) + COL_GAP * (len(row) - 1)
    total_w = max(widths.values()) if widths else 400

    geo, bands, y = {}, {}, PAD_Y
    for r in sorted(rows):
        # One height per row, driven by the tallest member, so box bottoms align
        # and the connectors leaving them start on a common line.
        h = NODE_H[max(_lines(nd) for nd in rows[r])]
        x = PAD_X + (total_w - widths[r]) / 2
        for nd in rows[r]:
            w = _node_w(nd)
            geo[nd["id"]] = {"x": x, "y": y, "w": w, "h": h, "nd": nd}
            x += w + COL_GAP
        bands[r] = (y, y + h)
        y += h + ROW_GAP

    return geo, total_w, y - ROW_GAP + PAD_Y, bands


def _adjacent_path(a, b) -> str:
    """Route between neighbouring rows: down, across the gap, down.

    Safe by construction *only* for adjacent rows, because the horizontal leg
    sits at the midpoint between them, and that band contains no nodes. Used for
    a non-adjacent pair it would cross every row in between — which is exactly
    the bug the structural checker caught.
    """
    ax, ay = a["x"] + a["w"] / 2, a["y"] + a["h"]
    bx, by = b["x"] + b["w"] / 2, b["y"]
    if abs(ax - bx) < 1.5:
        return f"M{ax:.1f} {ay:.1f} L{bx:.1f} {by - 5:.1f}"
    mid = ay + (by - ay) / 2
    return (f"M{ax:.1f} {ay:.1f} L{ax:.1f} {mid:.1f} "
            f"L{bx:.1f} {mid:.1f} L{bx:.1f} {by - 5:.1f}")


def _lane_path(a, b, lane_x, gap_out, gap_in) -> str:
    """Route via a margin lane for any pair that is not on adjacent rows.

    Five legs, and every one of them is in provably empty space:

        1. straight down out of the source into `gap_out`   (its own column)
        2. across `gap_out` to the lane                     (inter-row band)
        3. along the lane to `gap_in`                       (beyond all nodes)
        4. across `gap_in` to the target's column           (inter-row band)
        5. straight down into the target's top edge         (its own column)

    Leg 2 is the one that matters. An earlier version left the source
    *sideways* at its own mid-height, which crosses any node sharing that row —
    caught by check_arch C2. Horizontal travel only happens in inter-row gaps,
    which hold no nodes by construction.
    """
    ax = a["x"] + a["w"] / 2
    bx = b["x"] + b["w"] / 2
    return (f"M{ax:.1f} {a['y'] + a['h']:.1f} L{ax:.1f} {gap_out:.1f} "
            f"L{lane_x:.1f} {gap_out:.1f} L{lane_x:.1f} {gap_in:.1f} "
            f"L{bx:.1f} {gap_in:.1f} L{bx:.1f} {b['y'] - 5:.1f}")


def render_diagram(spec: dict) -> str:
    nodes, edges = spec["nodes"], spec.get("edges", [])
    groups, caption = spec.get("groups", []), spec.get("caption", "")

    layer, fwd, back = _layer(nodes, edges)
    geo, w, h, bands = _place(nodes, layer, groups)

    # Two lanes, both outside every node's x-extent. Forward edges that skip a
    # row use the left one, back edges the right, so the two families never
    # share a lane and overlay each other.
    lane_r = PAD_X + w + 26
    lane_l = PAD_X / 2
    needs_lane = any(layer[e["to"]] - layer[e["from"]] > 1 for e in fwd)
    width = lane_r + (150 if back else 0)

    last = max(bands)

    def gap_above(lyr: int) -> float:
        """Midpoint of the node-free band above a row. Row 0 has no row above
        it, so it borrows the top padding."""
        return PAD_Y / 2 if lyr <= 0 else (bands[lyr - 1][1] + bands[lyr][0]) / 2

    def gap_below(lyr: int) -> float:
        """Same, below. The last row borrows the bottom padding."""
        return (bands[lyr][1] + PAD_Y / 2 if lyr >= last
                else (bands[lyr][1] + bands[lyr + 1][0]) / 2)

    def route(e) -> str:
        fl, tl = layer[e["from"]], layer[e["to"]]
        a, b = geo[e["from"]], geo[e["to"]]
        if tl == fl + 1:
            return _adjacent_path(a, b)
        lane = lane_l if tl > fl else lane_r
        return _lane_path(a, b, lane, gap_below(fl), gap_above(tl))

    p = [f'<div class="figwrap"><svg viewBox="0 0 {width:.0f} {h:.0f}" '
         f'width="{width:.0f}" height="{h:.0f}" role="img" '
         f'aria-label="{html.escape(caption or "architecture diagram")}">']

    for g in groups:
        ms = [geo[m] for m in g.get("members", []) if m in geo]
        if not ms:
            continue
        gx = min(m["x"] for m in ms) - GROUP_PAD
        gy = min(m["y"] for m in ms) - GROUP_PAD - 10
        gw = max(m["x"] + m["w"] for m in ms) - gx + GROUP_PAD
        gh = max(m["y"] + m["h"] for m in ms) - gy + GROUP_PAD
        p.append(f'<rect class="grp" x="{gx:.0f}" y="{gy:.0f}" '
                 f'width="{gw:.0f}" height="{gh:.0f}" rx="3"/>')
        p.append(f'<text class="grpl" x="{gx + 8:.0f}" y="{gy + 12:.0f}">'
                 f'{html.escape(g["label"])}</text>')

    for e in fwd + back:
        a, b = geo[e["from"]], geo[e["to"]]
        d = route(e)
        is_back = layer[e["to"]] <= layer[e["from"]]
        if not is_back:
            p.append(f'<path class="wire" d="{d}"/>')
        if e.get("style") != "static" or is_back:
            p.append(f'<path class="wire-a" d="{d}"/>')
        if e.get("label"):
            if is_back:
                lx, ly = lane_r + 6, (a["y"] + b["y"]) / 2
            elif layer[e["to"]] == layer[e["from"]] + 1:
                lx = (a["x"] + a["w"] / 2 + b["x"] + b["w"] / 2) / 2 + 7
                ly = a["y"] + a["h"] + (b["y"] - a["y"] - a["h"]) / 2 - 4
            else:
                lx, ly = lane_l + 5, (a["y"] + b["y"]) / 2
            p.append(f'<text class="wlab" x="{lx:.0f}" y="{ly:.0f}">'
                     f'{html.escape(e["label"])}</text>')

    for g in geo.values():
        nd = g["nd"]
        p.append(f'<rect class="nd nd-{nd.get("kind", "module")}" x="{g["x"]:.0f}" '
                 f'y="{g["y"]:.0f}" width="{g["w"]:.0f}" height="{g["h"]:.0f}" rx="3"/>')
        x = g["x"] + 11
        # Single-line nodes centre; multi-line nodes stack from a fixed top so
        # the label sits on the same baseline across a row.
        ty = g["y"] + (g["h"] / 2 + 4 if _lines(nd) == 1 else 21)
        p.append(f'<text class="ndl" x="{x:.0f}" y="{ty:.0f}">{html.escape(nd["label"])}</text>')
        if nd.get("sub"):
            p.append(f'<text class="nds" x="{x:.0f}" y="{ty + 14:.0f}">'
                     f'{html.escape(nd["sub"])}</text>')
        if nd.get("tech"):
            # Technology reads as an annotation, not description — bracketed and
            # in the accent colour so the eye can pick out "what is this built
            # from" without reading every box.
            ty_t = ty + (28 if nd.get("sub") else 14)
            p.append(f'<text class="ndt" x="{x:.0f}" y="{ty_t:.0f}">'
                     f'[{html.escape(nd["tech"])}]</text>')

    p.append("</svg>")
    if caption:
        p.append(f'<div class="figcap">{_inline(caption)}</div>')
    p.append("</div>")
    return "".join(p)


# ════════════════════════════════════════════════════════════════════════════
# page
# ════════════════════════════════════════════════════════════════════════════

def parse_frontmatter(md: str) -> tuple[dict, str]:
    if not md.startswith("---"):
        return {}, md
    end = md.index("\n---", 3)
    meta = {}
    for ln in md[3:end].strip().split("\n"):
        if ":" in ln:
            k, v = ln.split(":", 1)
            meta[k.strip()] = v.strip().strip('"').strip("'")
    return meta, md[end + 4:]


TEMPLATE = """<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="source-sha256" content="{src_hash}">
<meta name="renderer-sha256" content="{gen_hash}">
<title>{title}</title>
<style>
:root{{
  --void:#060908; --panel:#0C1211; --panel2:#101817;
  --edge:#1C2827; --edge2:#283735;
  --accent:{accent}; --accent-dim:{accent}18; --accent-glow:{accent}66;
  --phos:#4BE38A; --phos-dim:#4BE38A14; --red:#E8664F;
  --txt:#D6E0DD; --mid:#7C8B87; --faint:#4E5C58;
  --mono:ui-monospace,"SF Mono",SFMono-Regular,Menlo,Consolas,monospace;
}}
body{{background:var(--void);color:var(--txt);font-family:var(--mono);
  font-size:13px;line-height:1.65;-webkit-font-smoothing:antialiased}}
body::before{{content:"";position:fixed;inset:0;pointer-events:none;z-index:99;
  background:repeating-linear-gradient(180deg,transparent 0 2px,rgba(0,0,0,.22) 2px 3px);opacity:.5}}
.rig{{max-width:70rem;margin:0 auto;padding:0 clamp(.75rem,3vw,1.75rem) 4rem}}
.bar{{border:1px solid var(--edge);background:linear-gradient(180deg,var(--panel2),var(--panel));
  display:flex;flex-wrap:wrap;align-items:center;gap:.85rem;padding:.8rem 1.1rem;
  position:sticky;top:0;z-index:50;margin-bottom:.4rem}}
.led{{width:7px;height:7px;border-radius:50%;background:var(--phos);box-shadow:0 0 8px var(--phos)}}
@media (prefers-reduced-motion:no-preference){{.led{{animation:blip 2.4s ease-in-out infinite}}}}
@keyframes blip{{0%,100%{{opacity:1}}50%{{opacity:.35}}}}
h1{{margin:0;font-size:1.05rem;font-weight:600;letter-spacing:.07em;color:var(--accent);
  text-shadow:0 0 14px var(--accent-glow)}}
.tag{{font-size:.58rem;letter-spacing:.15em;text-transform:uppercase;color:var(--faint);
  border:1px solid var(--edge2);padding:.1rem .4rem}}
.spacer{{flex:1}}
nav{{display:flex;flex-wrap:wrap;gap:.65rem;font-size:.6rem;letter-spacing:.09em}}
nav a{{color:var(--mid);text-decoration:none;text-transform:uppercase}}
nav a:hover{{color:var(--accent)}}
h2{{margin:2.2rem 0 0;font-size:.76rem;font-weight:600;letter-spacing:.17em;text-transform:uppercase;
  color:var(--accent);border-bottom:1px solid var(--edge);padding-bottom:.45rem;scroll-margin-top:4.5rem}}
h3{{margin:1.5rem 0 0;font-size:.7rem;font-weight:600;letter-spacing:.11em;text-transform:uppercase;color:var(--txt)}}
p{{margin:.75rem 0 0;max-width:78ch;color:var(--mid)}}
p strong{{color:var(--txt);font-weight:600}}
code{{color:var(--phos);background:var(--phos-dim);padding:.06em .28em;font-size:.9em}}
a{{color:var(--accent)}}
ul,ol{{margin:.75rem 0 0;padding-left:1.35rem;color:var(--mid);display:flex;flex-direction:column;gap:.35rem}}
li{{max-width:76ch}}
ol li::marker{{color:var(--accent);font-size:.85em}}
hr{{border:0;border-top:1px solid var(--edge);margin:1.8rem 0 0}}
blockquote{{margin:.9rem 0 0;padding:.1rem 0 .1rem 1rem;border-left:2px solid var(--accent)}}
blockquote p{{margin:.5rem 0 0;color:var(--mid)}}
blockquote p:first-child{{margin-top:0}}
pre{{margin:.85rem 0 0;background:var(--panel);border:1px solid var(--edge);padding:.7rem .85rem;
  overflow-x:auto;font-size:.76rem;color:var(--mid)}}
.tw{{overflow-x:auto;margin:.9rem 0 0;border:1px solid var(--edge);background:var(--panel)}}
table{{width:100%;min-width:30rem;border-collapse:collapse;font-size:.75rem}}
th,td{{text-align:left;padding:.45rem .7rem;border-bottom:1px solid var(--edge);vertical-align:top}}
thead th{{font-size:.57rem;letter-spacing:.14em;text-transform:uppercase;color:var(--faint);font-weight:400}}
tbody tr:last-child td{{border-bottom:0}}
td{{color:var(--mid)}} td code{{color:var(--phos)}}
.figwrap{{margin:1.1rem 0 0;border:1px solid var(--edge);background:
  radial-gradient(ellipse at 50% 40%,#0E1614 0%,#070B0A 82%);overflow-x:auto}}
.figwrap svg{{display:block;margin:0 auto}}
.figcap{{border-top:1px solid var(--edge);padding:.45rem .8rem;font-size:.66rem;color:var(--faint)}}
.nd{{fill:var(--panel2);stroke:var(--edge2);stroke-width:1}}
.nd-store{{stroke:var(--phos);fill:#0D1614}}
.nd-external{{stroke:var(--edge2);stroke-dasharray:4 3;fill:#0A0F0E}}
.nd-service{{stroke:var(--accent)}}
.nd-secret{{stroke:var(--red);fill:#160C0A}}
.ndl{{font-size:10.5px;fill:var(--txt);font-family:var(--mono)}}
.nds{{font-size:8px;fill:var(--faint);font-family:var(--mono)}}
.ndt{{font-size:7.5px;fill:var(--accent);font-family:var(--mono);opacity:.85;letter-spacing:.04em}}
.wire{{fill:none;stroke:var(--edge2);stroke-width:1}}
.wire-a{{fill:none;stroke:var(--accent);stroke-width:1.2;stroke-dasharray:3 5;opacity:.9}}
@media (prefers-reduced-motion:no-preference){{
  .wire-a{{animation:mv .75s linear infinite}} @keyframes mv{{to{{stroke-dashoffset:-8}}}}
}}
.paused .wire-a,.paused .led{{animation-play-state:paused}}
.wlab{{font-size:8px;fill:var(--faint);font-family:var(--mono)}}
.grp{{fill:none;stroke:var(--accent);stroke-dasharray:7 4;opacity:.4}}
.grpl{{font-size:8px;fill:var(--accent);font-family:var(--mono);letter-spacing:.11em}}
footer{{margin-top:3rem;border-top:1px solid var(--edge);padding-top:.9rem;display:flex;
  flex-wrap:wrap;gap:1rem;align-items:center;font-size:.6rem;color:var(--faint);letter-spacing:.08em}}
button.pz{{font-family:var(--mono);font-size:.6rem;background:transparent;color:var(--accent);
  border:1px solid var(--edge2);padding:.2rem .55rem;cursor:pointer;letter-spacing:.08em}}
button.pz:hover{{border-color:var(--accent)}}
:focus-visible{{outline:1px solid var(--accent);outline-offset:2px}}
</style>

<div class="rig">
<header class="bar">
  <span class="led" aria-hidden="true"></span>
  <h1>{repo}</h1>
  {tags}
  <span class="spacer"></span>
  <nav>{nav}</nav>
</header>
{body}
<footer>
  <span>GENERATED FROM DOCS/ARCHITECTURE.MD — DO NOT EDIT THIS FILE</span>
  <span>STRUCTURE ONLY, NO RUNTIME STATE</span>
  <button class="pz" id="pz" aria-pressed="false">&#9208; PAUSE</button>
</footer>
</div>
<script>
(function(){{
  var b=document.getElementById('pz'),p=false;
  b.addEventListener('click',function(){{
    p=!p;document.body.classList.toggle('paused',p);
    b.setAttribute('aria-pressed',String(p));
    b.textContent=p?'\\u25B6 RESUME':'\\u23F8 PAUSE';
    Array.prototype.forEach.call(document.querySelectorAll('svg'),function(s){{
      if(p&&s.pauseAnimations)s.pauseAnimations();
      if(!p&&s.unpauseAnimations)s.unpauseAnimations();
    }});
  }});
}})();
</script>
"""


SRC_HASH_RE = re.compile(r'<meta name="source-sha256" content="([0-9a-f]{64})">')
GEN_HASH_RE = re.compile(r'<meta name="renderer-sha256" content="([0-9a-f]{64})">')


def _src_hash(md_path: Path) -> str:
    return hashlib.sha256(md_path.read_bytes()).hexdigest()


def _gen_hash() -> str:
    """Hash of this file. The source hash alone is not enough: change the
    renderer and every previously-generated page is stale while its source is
    untouched. On one repo that is a nuisance; across six it is six pages
    silently disagreeing with the tool that claims to produce them."""
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def build(md_path: Path) -> str:
    meta, body_md = parse_frontmatter(md_path.read_text())
    body = render_markdown(body_md)

    repo = meta.get("applies_to", md_path.parents[1].name)
    tags = "".join(f'<span class="tag">{html.escape(t)}</span>'
                   for t in meta.get("stage", "").split() if t)
    nav = "".join(
        f'<a href="#{m.group(1)}">{html.escape(re.sub("<[^>]+>", "", m.group(2)))}</a>'
        for m in re.finditer(r'<h2 id="([^"]+)">(.*?)</h2>', body)
    )
    return TEMPLATE.format(
        title=f"{repo} — Architecture",
        repo=html.escape(repo.upper()),
        accent=meta.get("accent", "#F5A623"),
        src_hash=_src_hash(md_path), gen_hash=_gen_hash(),
        tags=tags, nav=nav, body=body,
    )


def staleness(md_path: Path, html_path: Path) -> str | None:
    """Why `html_path` is out of date, or None if it is current.

    Content hashes, deliberately NOT mtimes. git does not preserve mtimes, so a
    checkout or a merge reorders them and an mtime comparison reports STALE on a
    file that is byte-for-byte current — which fired on the first merge of this
    tool. Both the source and the renderer are hashed: change the renderer and
    every page it produced is stale while its source is untouched, which across a
    fleet of repos is many pages silently disagreeing with the tool that claims
    to generate them.

    One implementation, two callers: this CLI and `check.py`. Duplicating it
    would let the two answers drift, which is the same class of bug as the
    markdown block list that drifted from its paragraph terminator.
    """
    if not html_path.exists():
        return "does not exist — render it"
    rendered = html_path.read_text()
    ms, mg = SRC_HASH_RE.search(rendered), GEN_HASH_RE.search(rendered)
    if not ms or not mg:
        return "has no provenance hashes — re-render"
    if ms.group(1) != _src_hash(md_path):
        return f"was built from a different {md_path.name} — re-render"
    if mg.group(1) != _gen_hash():
        return f"was built by an older {Path(__file__).name} — re-render"
    return None


def is_current(md_path: Path, html_path: Path) -> bool:
    return staleness(md_path, html_path) is None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("repo", nargs="?", type=Path, default=Path.cwd(),
                    help="repo to render (default: cwd)")
    ap.add_argument("-i", "--input", type=Path, default=None)
    ap.add_argument("-o", "--output", type=Path, default=None)
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if the html is missing or older than the md")
    args = ap.parse_args()
    d_in, d_out = _default_paths(args.repo.resolve())
    args.input = args.input or d_in
    args.output = args.output or d_out

    if not args.input.exists():
        print(f"missing {args.input}", file=sys.stderr)
        return 2

    if args.check:
        reason = staleness(args.input, args.output)
        if reason:
            print(f"STALE  {args.output.name} {reason}")
            return 1
        print(f"OK     {args.output.name} matches {args.input.name} and this renderer")
        return 0

    args.output.write_text(build(args.input))
    print(f"wrote {args.output}  ({args.output.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
