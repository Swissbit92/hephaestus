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
    """Markdown subset -> HTML, with ```archview/```archflow/```html handled specially."""
    lines = md.split("\n")
    out: list[str] = []
    i, n = 0, len(lines)

    # Views seen so far, keyed by their archview id. A single forward pass, so an
    # archflow can only reference a view declared *above* it — which is also how
    # the page reads, diagram first and then the walk through it.
    views: dict[str, dict] = {}
    fig_index = 0
    # Page-scoped, so two archflow blocks over the same view cannot both claim
    # one flow id and emit two elements sharing a DOM id.
    claimed_flows: set = set()

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
                fig_index += 1
                spec = json.loads(body)
                # An unnamed view still gets a stable handle, so adding an `id`
                # later is an edit to one block rather than a renumbering.
                views[spec.get("id") or f"f{fig_index}"] = {
                    "fig": fig_index, "spec": spec,
                }
                out.append(render_diagram(spec, fig_index))
            elif lang == "archflow":
                out.append(render_flow(json.loads(body), views, claimed_flows))
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

def _slug_id(s: str) -> str:
    """A DOM-safe fragment of an author-written id.

    archview ids are authored for readability, not for HTML — they carry dots,
    slashes and spaces. Those are legal in an `id` attribute under HTML5 but
    break `querySelector`/CSS selectors without escaping, which is exactly the
    kind of bug that only shows up on the one repo whose node happens to be
    called `exchange.py`.
    """
    return re.sub(r"[^A-Za-z0-9_-]+", "-", s).strip("-").lower() or "x"


def _node_aria(nd: dict) -> str:
    """One accessible name per node, assembled from the three visible lines.

    Deliberately `aria-label` and not a `<title>` child: `<title>` renders as a
    native browser tooltip on hover, which fights the flow caption that archflow
    puts on screen. The label is invisible and never collides.
    """
    parts = [nd["label"]]
    if nd.get("sub"):
        parts.append(nd["sub"])
    if nd.get("tech"):
        parts.append(f'built with {nd["tech"]}')
    return html.escape(" — ".join(parts))


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


CHAIN_MIN = 4          # below this a column is fine and wrapping just looks odd
CHAIN_MAX_W = 1180     # wrap before the figure needs horizontal scrolling


def _chain_order(nodes, edges):
    """The node order if this graph is one unbranched path, else None.

    A pipeline is a path: seven steps, each following exactly one other. Laid out
    by the general layerer that becomes seven rows — a column of boxes roughly
    800px tall, which is strictly worse than the numbered list it replaced. So a
    path is detected and laid out differently, and everything else is untouched.
    """
    if len(nodes) < CHAIN_MIN:
        return None
    ids = {nd["id"] for nd in nodes}
    if len(edges) != len(nodes) - 1:
        return None
    nxt, indeg = {}, {nid: 0 for nid in ids}
    for e in edges:
        if e["from"] in nxt or e.get("style") == "static":
            return None                      # a branch, or a non-flow relation
        nxt[e["from"]] = e["to"]
        indeg[e["to"]] = indeg.get(e["to"], 0) + 1
    if any(v > 1 for v in indeg.values()):
        return None
    starts = [nid for nid in ids if indeg[nid] == 0]
    if len(starts) != 1:
        return None
    order, seen, cur = [], set(), starts[0]
    while cur is not None:
        if cur in seen:
            return None                      # a cycle is not a chain
        seen.add(cur)
        order.append(cur)
        cur = nxt.get(cur)
    return order if len(order) == len(ids) else None


def _place_chain(nodes, order):
    """Serpentine rows: left-to-right, then right-to-left on the row below.

    Consecutive steps end up either side by side or directly stacked, so every
    connector is a straight line through empty space — no lanes, no crossings,
    and the reader's eye never jumps back across the figure to find step 5.
    """
    by_id = {nd["id"]: nd for nd in nodes}
    seq = [by_id[nid] for nid in order]

    # How many fit per row before we exceed the wrap width.
    per, acc = 0, 0.0
    for nd in seq:
        w = _node_w(nd)
        step = w if per == 0 else w + COL_GAP
        if acc + step > CHAIN_MAX_W and per:
            break
        acc += step
        per += 1
    per = max(2, per)
    rows = [seq[i:i + per] for i in range(0, len(seq), per)]

    row_h = [NODE_H[max(_lines(nd) for nd in r)] for r in rows]
    widest = max(sum(_node_w(nd) for nd in r) + COL_GAP * (len(r) - 1) for r in rows)

    geo, y = {}, PAD_Y
    for r, row in enumerate(rows):
        cells = list(row) if r % 2 == 0 else list(reversed(row))
        used = sum(_node_w(nd) for nd in cells) + COL_GAP * (len(cells) - 1)
        # Odd rows hug the right edge so the wrap lands directly under the last
        # box of the row above rather than diagonally across the figure.
        x = PAD_X if r % 2 == 0 else PAD_X + (widest - used)
        for nd in cells:
            w = _node_w(nd)
            geo[nd["id"]] = {"x": x, "y": y, "w": w, "h": row_h[r], "nd": nd}
            x += w + COL_GAP
        y += row_h[r] + ROW_GAP

    return geo, widest, y - ROW_GAP + PAD_Y


def _chain_edge(a, b) -> str:
    """Straight across within a row, straight down at the wrap."""
    if abs(a["y"] - b["y"]) < 1:                       # same row, side by side
        x1 = a["x"] + a["w"] if b["x"] > a["x"] else a["x"]
        x2 = b["x"] - 5 if b["x"] > a["x"] else b["x"] + b["w"] + 5
        yc = a["y"] + a["h"] / 2
        return f"M{x1:.1f} {yc:.1f} L{x2:.1f} {yc:.1f}"
    ax = a["x"] + a["w"] / 2
    bx = b["x"] + b["w"] / 2
    if abs(ax - bx) < 1.5:                             # stacked, straight drop
        return f"M{ax:.1f} {a['y'] + a['h']:.1f} L{bx:.1f} {b['y'] - 5:.1f}"
    mid = (a["y"] + a["h"] + b["y"]) / 2
    return (f"M{ax:.1f} {a['y'] + a['h']:.1f} L{ax:.1f} {mid:.1f} "
            f"L{bx:.1f} {mid:.1f} L{bx:.1f} {b['y'] - 5:.1f}")


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


def render_diagram(spec: dict, fig: int = 1) -> str:
    """Lay out and emit one diagram.

    `fig` scopes every emitted DOM id. A page may carry several diagrams, and two
    of them naming a node `wallet` would otherwise collide into duplicate ids —
    invalid HTML, and a `getElementById` that silently returns the wrong box.
    """
    nodes, edges = spec["nodes"], spec.get("edges", [])
    groups, caption = spec.get("groups", []), spec.get("caption", "")

    # A pure path gets the serpentine treatment; anything that branches keeps the
    # layered engine. The two share every emission path below — only placement
    # and connector routing differ.
    chain = _chain_order(nodes, edges) if not groups else None
    if chain:
        geo, w, h = _place_chain(nodes, chain)
        fwd, back = list(edges), []
        width = PAD_X + w + PAD_X
        route = lambda e: _chain_edge(geo[e["from"]], geo[e["to"]])  # noqa: E731
        layer = {nid: k for k, nid in enumerate(chain)}
    else:
        layer, fwd, back = _layer(nodes, edges)
        geo, w, h, bands = _place(nodes, layer, groups)

        # Two lanes, both outside every node's x-extent. Forward edges that skip
        # a row use the left one, back edges the right, so the two families never
        # share a lane and overlay each other.
        lane_r = PAD_X + w + 26
        lane_l = PAD_X / 2
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

    p = [f'<div class="figwrap"><svg id="fig-f{fig}" viewBox="0 0 {width:.0f} {h:.0f}" '
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
        # data-* rides on the <rect> here because check_arch's RE_RECT tolerates
        # attributes between class and x. RE_PATH does not — see the edge loop.
        p.append(f'<rect class="grp" data-group="{html.escape(g["id"])}" '
                 f'x="{gx:.0f}" y="{gy:.0f}" '
                 f'width="{gw:.0f}" height="{gh:.0f}" rx="3"/>')
        p.append(f'<text class="grpl" x="{gx + 8:.0f}" y="{gy + 12:.0f}">'
                 f'{html.escape(g["label"])}</text>')

    for e in fwd + back:
        a, b = geo[e["from"]], geo[e["to"]]
        d = route(e)
        is_back = layer[e["to"]] <= layer[e["from"]]
        # Identity goes on a wrapping <g>, never on the <path> itself.
        # check_arch.RE_PATH is r'<path class="([^"]*)" d="([^"]*)"' — it requires
        # d to follow class with nothing in between. Slipping an id or data-* in
        # there stops it matching *any* connector, so every page would pass while
        # checking zero edges. A silent, total loss of the geometry gate.
        # Two attributes, not one joined key. Any delimiter can appear inside a
        # node id — `a -> b__c` and `a__b -> c` both flatten to "a__b__c" — and
        # the failure is silent: querySelector returns the first match, so a step
        # highlights the wrong edge and nothing says so.
        p.append(f'<g data-edge-from="{html.escape(e["from"])}" '
                 f'data-edge-to="{html.escape(e["to"])}">')
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
        p.append("</g>")

    for g in geo.values():
        nd = g["nd"]
        p.append(f'<g id="f{fig}-nd-{_slug_id(nd["id"])}" '
                 f'data-node="{html.escape(nd["id"])}" '
                 f'role="graphics-symbol" aria-label="{_node_aria(nd)}">')
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
        p.append("</g>")

    p.append("</svg>")
    p.append(_legend(nodes))
    p.append(_alt_table(spec))
    if caption:
        p.append(f'<div class="figcap">{_inline(caption)}</div>')
    p.append("</div>")
    return "".join(p)


# The border language only means something if the page says what it means. Built
# from the kinds actually present, so a diagram with no secrets does not carry a
# swatch for one.
KIND_MEANING = {
    "module": "code in this repo",
    "service": "a process or entry point",
    "store": "a database, table, queue or bucket",
    "external": "something you do not control",
    "secret": "a credential store",
}


def _legend(nodes: list) -> str:
    used = []
    for nd in nodes:
        k = nd.get("kind", "module")
        if k not in used and k in KIND_MEANING:
            used.append(k)
    if len(used) < 2:
        return ""                       # one kind explains itself
    # CSS swatches, not <svg> ones. check_arch finds diagrams by matching any
    # <svg> carrying a viewBox, so an SVG legend gets counted and geometry-checked
    # as if it were a sixth architecture diagram — it reported "6 diagrams" on a
    # page with one. A span cannot be mistaken for a figure.
    items = "".join(
        f'<span class="lgi"><span class="lgs lgs-{k}" aria-hidden="true"></span>'
        f'{html.escape(KIND_MEANING[k])}</span>'
        for k in used
    )
    return f'<div class="legend">{items}</div>'


class ArchFlowError(ValueError):
    """A flow points at something that is not in the diagram.

    Raised at build time, not lint time. A dangling reference is not a geometry
    problem, so `check_arch.py` — which only ever reads the emitted SVG — cannot
    see it. Catching it here means a typo fails the render loudly instead of
    shipping a picker whose third step highlights nothing.
    """


def render_flow(spec: dict, views: dict, claimed: set | None = None) -> str:
    """Render the walker for one ```archflow``` block.

    `claimed` accumulates (figure, slug) pairs across *every* archflow block on
    the page. Scoping it to one call was a real hole: a page that splits its happy
    path and its error path into two blocks over the same view could declare the
    same flow id twice and emit two elements with one DOM id, silently.
    """
    claimed = claimed if claimed is not None else set()
    view_id = spec.get("view")
    if view_id not in views:
        raise ArchFlowError(
            f"archflow references view {view_id!r}, which is not declared above it. "
            f"Views available at this point: {sorted(views) or '(none)'}. "
            f"An archflow block must follow the archview it walks through."
        )
    entry = views[view_id]
    vspec, fig = entry["spec"], entry["fig"]
    node_ids = {nd["id"] for nd in vspec["nodes"]}
    edge_ids = {(e["from"], e["to"]) for e in vspec.get("edges", [])}

    flows = spec.get("flows", [])
    for fl in flows:
        for required in ("id", "label"):
            if not fl.get(required):
                raise ArchFlowError(
                    f"a flow in view {view_id!r} is missing {required!r}. "
                    f"Every flow needs an id (for the deep link) and a label "
                    f"(for the picker). Got keys: {sorted(fl)}"
                )
        fid = fl["id"]
        # Collide on the *slug*, not the raw id. "Flow A" and "Flow-A" are two
        # distinct strings that become one DOM id, which is exactly the kind of
        # duplicate that renders fine and then misbehaves.
        key = (fig, _slug_id(fid))
        if key in claimed:
            raise ArchFlowError(
                f"flow id {fid!r} collides with another flow on view "
                f"{view_id!r} (both become {_slug_id(fid)!r})"
            )
        claimed.add(key)
        for k, st in enumerate(fl.get("steps", []), 1):
            has = ("node" in st) + ("edge" in st)
            if has != 1:
                raise ArchFlowError(
                    f"flow {fid!r} step {k} must carry exactly one of "
                    f"'node' or 'edge', got {sorted(st)}"
                )
            if "node" in st and st["node"] not in node_ids:
                raise ArchFlowError(
                    f"flow {fid!r} step {k} points at node {st['node']!r}, "
                    f"absent from view {view_id!r}. Nodes: {sorted(node_ids)}"
                )
            if "edge" in st:
                pair = tuple(st["edge"])
                if pair not in edge_ids:
                    raise ArchFlowError(
                        f"flow {fid!r} step {k} points at edge {pair}, absent "
                        f"from view {view_id!r}. Edges: {sorted(edge_ids)}"
                    )

    opts, data = [], []
    for k, fl in enumerate(flows):
        opts.append(
            f'<li role="option" id="fo-{fig}-{_slug_id(fl["id"])}" '
            f'data-flow="{html.escape(fl["id"])}" tabindex="-1" '
            f'aria-selected="{"true" if k == 0 else "false"}">'
            f'{html.escape(fl["label"])}</li>'
        )
        steps = [
            {"t": "node", "k": st["node"], "note": st.get("note", "")}
            if "node" in st else
            {"t": "edge", "f": st["edge"][0], "to": st["edge"][1],
             "note": st.get("note", "")}
            for st in fl.get("steps", [])
        ]
        data.append({"id": fl["id"], "label": fl["label"], "steps": steps})

    payload = html.escape(json.dumps(data, separators=(",", ":")), quote=True)
    return (
        f'<div class="flowctl" data-view="fig-f{fig}" data-flows="{payload}">'
        f'<div class="flowhd">'
        f'<span class="flowlbl" id="fl-{fig}-lbl">Walk a flow</span>'
        f'<a class="flowjump" href="#fig-f{fig}">jump to diagram &#8593;</a>'
        f'</div>'
        f'<ul class="flowlist" role="listbox" aria-labelledby="fl-{fig}-lbl" '
        f'tabindex="0">{"".join(opts)}</ul>'
        f'<div class="flownav">'
        f'<button class="pz" type="button" data-flow-prev disabled>&#8592; prev</button>'
        f'<span class="flowpos" data-flow-pos>&#8212;</span>'
        f'<button class="pz" type="button" data-flow-next disabled>next &#8594;</button>'
        f'<button class="pz flowclear" type="button" data-flow-clear>clear</button>'
        f'</div>'
        f'<p class="flowcap" data-flow-cap role="status" aria-live="polite" '
        f'aria-atomic="true">Select a flow to trace it through the diagram.</p>'
        f'</div>'
    )


def _alt_table(spec: dict) -> str:
    """The diagram as a table, for anyone who cannot see the diagram.

    A layered DAG carries its meaning in position and connection, and neither
    survives an `aria-label` on the <svg>. Since the model is already structured
    JSON, the honest text alternative is free — so there is no excuse for the
    usual one-sentence summary that tells a screen-reader user nothing.
    """
    nodes = spec["nodes"]
    edges = spec.get("edges", [])
    by_id = {nd["id"]: nd for nd in nodes}

    rows = []
    for nd in nodes:
        outs = [e for e in edges if e["from"] == nd["id"]]
        if outs:
            conn = "; ".join(
                f'{html.escape(by_id.get(e["to"], {}).get("label", e["to"]))}'
                + (f' ({html.escape(e["label"])})' if e.get("label") else "")
                for e in outs
            )
        else:
            conn = "—"
        rows.append(
            f'<tr><td>{html.escape(nd["label"])}</td>'
            f'<td>{html.escape(KIND_MEANING.get(nd.get("kind", "module"), "component"))}</td>'
            f'<td>{html.escape(nd.get("sub", "") or "—")}</td>'
            f'<td>{conn}</td></tr>'
        )
    cap = html.escape(spec.get("caption", "") or "Diagram contents")
    return (
        f'<table class="sr-only"><caption>{cap} — text alternative</caption>'
        f'<thead><tr><th>Component</th><th>Kind</th><th>Role</th>'
        f'<th>Connects to</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table>'
    )


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
<script>
/* Before first paint, deliberately. Setting the theme after the stylesheet has
   painted shows the wrong one for a frame — the flash people notice and nobody
   can un-see. Dark stays the default when nothing is stored. */
(function(){{
  try{{
    var t=localStorage.getItem('arch-theme');
    if(!t) t=matchMedia('(prefers-color-scheme: light)').matches?'light':'dark';
    document.documentElement.setAttribute('data-theme',t);
  }}catch(e){{document.documentElement.setAttribute('data-theme','dark');}}
}})();
</script>
<style>
:root{{
  --void:#060908; --panel:#0C1211; --panel2:#101817;
  --edge:#1C2827; --edge2:#283735;
  --accent:{accent}; --accent-dim:{accent}18; --accent-glow:{accent}66;
  --phos:#4BE38A; --phos-dim:#4BE38A14; --red:#E8664F;
  /* Contrast, not taste. The old ramp put --faint at 2.85:1 on --void and --mid
     at 5.62:1; the dimmest tier carries table headers, figure captions and the
     8px sub-labels inside every diagram, so it failed WCAG AA exactly where the
     type is smallest. Lifting --faint alone would have collapsed it into --mid,
     so the whole ramp is re-spaced. Now 5.04 / 8.15 / 14.82 on --void, and the
     tightest of the three still clears 4.5:1 against --panel2. */
  --txt:#D6E0DD; --mid:#9CA8A5; --faint:#70847E;
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
button.pz[disabled]{{opacity:.4;cursor:default;border-color:var(--edge)}}
:focus-visible{{outline:1px solid var(--accent);outline-offset:2px}}

/* Visible to a screen reader, absent from the page. Not display:none, which
   removes it from the accessibility tree along with everything else. */
.sr-only{{position:absolute;width:1px;height:1px;padding:0;margin:-1px;
  overflow:hidden;clip:rect(0 0 0 0);clip-path:inset(50%);white-space:nowrap;border:0}}

.legend{{display:flex;flex-wrap:wrap;gap:.9rem;padding:.5rem .8rem;
  border-top:1px solid var(--edge);font-size:.62rem;color:var(--faint)}}
.lgi{{display:flex;align-items:center;gap:.35rem}}
.lgs{{width:15px;height:10px;flex:none;border-radius:2px;
  background:var(--panel2);border:1px solid var(--edge2)}}
.lgs-store{{border-color:var(--phos);background:#0D1614}}
.lgs-external{{border-style:dashed;background:#0A0F0E}}
.lgs-service{{border-color:var(--accent)}}
.lgs-secret{{border-color:var(--red);background:#160C0A}}
:root[data-theme="light"] .lgs{{background:#FFFFFF}}
:root[data-theme="light"] .lgs-store{{background:#F1F8F4}}
:root[data-theme="light"] .lgs-external{{background:#F5F7F6}}
:root[data-theme="light"] .lgs-secret{{background:#FDF3F1}}

/* ── flow walker ───────────────────────────────────────────────────────── */
.flowctl{{margin:.9rem 0 0;border:1px solid var(--edge);background:var(--panel)}}
.flowhd{{display:flex;align-items:baseline;gap:.8rem;padding:.5rem .8rem;
  border-bottom:1px solid var(--edge)}}
.flowlbl{{font-size:.6rem;letter-spacing:.14em;text-transform:uppercase;color:var(--faint)}}
.flowjump{{margin-left:auto;font-size:.6rem;color:var(--mid);text-decoration:none}}
.flowjump:hover{{color:var(--accent)}}
.flowlist{{list-style:none;margin:0;padding:.4rem;display:flex;flex-wrap:wrap;
  gap:.35rem}}
.flowlist li{{font-size:.66rem;padding:.2rem .55rem;border:1px solid var(--edge2);
  color:var(--mid);cursor:pointer;max-width:none}}
.flowlist li:hover{{border-color:var(--accent);color:var(--txt)}}
.flowlist li[aria-selected="true"]{{border-color:var(--accent);color:var(--accent);
  background:var(--accent-dim)}}
.flownav{{display:flex;align-items:center;gap:.5rem;padding:0 .8rem .5rem}}
.flowpos{{font-size:.6rem;color:var(--faint);letter-spacing:.08em;min-width:5rem}}
.flowclear{{margin-left:auto}}
.flowcap{{margin:0;padding:.5rem .8rem;border-top:1px solid var(--edge);
  font-size:.7rem;color:var(--mid);min-height:1.2rem}}

/* Dim with fill-opacity/stroke-opacity rather than `opacity`: the composite
   property promotes every element to its own compositing layer, which is real
   jank once a diagram has thirty boxes. These two are paint-only. */
svg.flowing .nd,svg.flowing .wire,svg.flowing .wire-a,
svg.flowing .ndl,svg.flowing .nds,svg.flowing .ndt,svg.flowing .wlab{{
  fill-opacity:.18;stroke-opacity:.18;transition:fill-opacity .18s,stroke-opacity .18s}}
svg.flowing [data-node].on-path .nd,svg.flowing [data-node].on-path .ndl,
svg.flowing [data-node].on-path .nds,svg.flowing [data-node].on-path .ndt,
svg.flowing [data-edge].on-path .wire,svg.flowing [data-edge].on-path .wire-a,
svg.flowing [data-edge].on-path .wlab{{fill-opacity:1;stroke-opacity:1}}
/* The current step has to win against the node-kind colours, which already use
   the accent. Border alone was ambiguous on a service node, so it also gets the
   accent wash and a halo. */
svg.flowing [data-node].at-step .nd{{stroke:var(--accent);stroke-width:2;
  fill:var(--accent-dim);filter:drop-shadow(0 0 6px var(--accent-glow))}}
svg.flowing [data-node].at-step .ndl{{fill:var(--accent)}}
svg.flowing [data-edge].at-step .wire-a{{stroke-width:2.6;
  filter:drop-shadow(0 0 5px var(--accent-glow))}}
@media (prefers-reduced-motion:reduce){{
  svg.flowing [data-node].at-step .nd,
  svg.flowing [data-edge].at-step .wire-a{{filter:none}}
}}

@media (prefers-reduced-motion:reduce){{
  svg.flowing .nd,svg.flowing .wire,svg.flowing .wire-a,
  svg.flowing .ndl,svg.flowing .nds,svg.flowing .ndt,svg.flowing .wlab{{transition:none}}
}}

/* ── light theme ───────────────────────────────────────────────────────────
   An attribute override, not light-dark(). The dark skin leans on glow —
   text-shadow, box-shadow, a scanline overlay — and those have to be switched
   off as a group, which a per-value colour function cannot express. */
:root[data-theme="light"]{{
  --void:#F4F6F5; --panel:#FFFFFF; --panel2:#F9FBFA;
  --edge:#D5DEDB; --edge2:#B9C6C2;
  --phos:#0F7A44; --phos-dim:#0F7A4414; --red:#B3341C;
  --txt:#12201C; --mid:#3F514C; --faint:#5A6B66;
}}
:root[data-theme="light"] body::before{{display:none}}
:root[data-theme="light"] h1{{text-shadow:none}}
:root[data-theme="light"] .led{{box-shadow:none}}
:root[data-theme="light"] .figwrap{{background:#FFFFFF}}
:root[data-theme="light"] .nd{{fill:#FFFFFF}}
:root[data-theme="light"] .nd-store{{fill:#F1F8F4}}
:root[data-theme="light"] .nd-external{{fill:#F5F7F6}}
:root[data-theme="light"] .nd-secret{{fill:#FDF3F1}}

/* ── print ─────────────────────────────────────────────────────────────────
   The scanline overlay and a near-black page background are a screen
   affectation; on paper they are a toner bill and an unreadable page. */
@media print{{
  :root{{
    --void:#FFFFFF; --panel:#FFFFFF; --panel2:#FFFFFF;
    --edge:#9AA8A4; --edge2:#6E7D79;
    --txt:#000000; --mid:#1C2A26; --faint:#3D4B47; --phos:#0A5C33;
  }}
  @page{{margin:14mm}}
  body{{background:#fff;font-size:10pt}}
  body::before{{display:none}}
  .bar{{position:static;border-bottom:1px solid var(--edge)}}
  nav,button.pz,.flownav,.flowjump{{display:none}}
  h1{{text-shadow:none}}
  .led{{box-shadow:none}}
  h2,h3{{break-after:avoid}}
  pre,table,.figwrap,.flowctl,blockquote{{break-inside:avoid}}
  .figwrap{{background:#fff}}
  .nd{{fill:#fff}}
  /* Every flow, spelled out — the picker is gone on paper, so the steps have to
     be readable as a list or the section says nothing. */
  .flowlist li{{border-color:var(--edge2)}}
  a{{color:inherit;text-decoration:underline}}
  a[href^="http"]::after{{content:" (" attr(href) ")";font-size:.8em;color:var(--faint)}}
}}
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
  {published}
  <span class="spacer"></span>
  <button class="pz" id="th" type="button">&#9681; LIGHT</button>
  <button class="pz" id="pz" type="button" aria-pressed="false">&#9208; PAUSE</button>
</footer>
</div>
<script>
(function(){{
  var doc=document.documentElement;
  /* One iteration helper. NodeList.forEach and Array.prototype.forEach.call were
     both in use here; picking one keeps the intent obvious. */
  function each(xs,fn){{Array.prototype.forEach.call(xs,fn);}}

  /* theme toggle */
  var t=document.getElementById('th');
  function paint(){{
    var light=doc.getAttribute('data-theme')==='light';
    t.textContent=light?'\\u25D1 DARK':'\\u25D1 LIGHT';
    t.setAttribute('aria-label',light?'Switch to dark theme':'Switch to light theme');
  }}
  paint();
  t.addEventListener('click',function(){{
    var next=doc.getAttribute('data-theme')==='light'?'dark':'light';
    doc.setAttribute('data-theme',next);
    try{{localStorage.setItem('arch-theme',next);}}catch(e){{}}
    paint();
  }});

  /* pause. The animation is CSS keyframes, so a class is the whole mechanism.
     The SVG animation-pause API this used to call drives SMIL, which no diagram
     on this page uses — it was a no-op dressed up as a feature. */
  var b=document.getElementById('pz'),p=false;
  b.addEventListener('click',function(){{
    p=!p;document.body.classList.toggle('paused',p);
    b.setAttribute('aria-pressed',String(p));
    b.textContent=p?'\\u25B6 RESUME':'\\u23F8 PAUSE';
  }});

  /* flow walker */
  each(document.querySelectorAll('.flowctl'),function(ctl){{
    var svg=document.getElementById(ctl.getAttribute('data-view'));
    if(!svg) return;
    var flows;
    try{{flows=JSON.parse(ctl.getAttribute('data-flows'));}}catch(e){{return;}}
    if(!flows||!flows.length) return;

    var list=ctl.querySelector('.flowlist'),
        cap=ctl.querySelector('[data-flow-cap]'),
        pos=ctl.querySelector('[data-flow-pos]'),
        prev=ctl.querySelector('[data-flow-prev]'),
        next=ctl.querySelector('[data-flow-next]'),
        clear=ctl.querySelector('[data-flow-clear]'),
        cur=-1,step=0;

    function marks(){{
      each(svg.querySelectorAll('.on-path,.at-step'),function(el){{
        el.classList.remove('on-path','at-step');
        el.removeAttribute('aria-current');
      }});
    }}
    function q(v){{return typeof CSS!=='undefined'&&CSS.escape?CSS.escape(v):v;}}
    function find(s){{
      return s.t==='node'
        ? svg.querySelector('[data-node="'+q(s.k)+'"]')
        : svg.querySelector('[data-edge-from="'+q(s.f)+'"][data-edge-to="'+q(s.to)+'"]');
    }}
    function draw(){{
      marks();
      if(cur<0){{
        svg.classList.remove('flowing');
        each(list.querySelectorAll('li'),function(li){{li.setAttribute('aria-selected','false');}});
        cap.textContent='Select a flow to trace it through the diagram.';
        pos.textContent='\\u2014';
        prev.disabled=next.disabled=true;
        return;
      }}
      var f=flows[cur];
      svg.classList.add('flowing');
      each(list.querySelectorAll('li'),function(li,k){{
        li.setAttribute('aria-selected',String(k===cur));
      }});
      each(f.steps,function(s){{
        var el=find(s); if(el) el.classList.add('on-path');
      }});
      var at=f.steps[step],el=at&&find(at);
      if(el){{el.classList.add('at-step');el.setAttribute('aria-current','step');}}
      pos.textContent='step '+(step+1)+' / '+f.steps.length;
      /* One whole-text write, not an append — partial updates get dropped. */
      cap.textContent=(at&&at.note)?at.note:f.label;
      prev.disabled=step<=0;
      next.disabled=step>=f.steps.length-1;
      try{{
        history.replaceState(null,'','#flow='+encodeURIComponent(f.id)+'&step='+(step+1));
      }}catch(e){{}}
    }}
    function pick(k,s){{cur=k;step=s||0;draw();}}

    list.addEventListener('click',function(e){{
      var li=e.target.closest('li'); if(!li) return;
      pick(Array.prototype.indexOf.call(list.children,li),0);
    }});
    list.addEventListener('keydown',function(e){{
      var k=e.key;
      if(k==='ArrowDown'||k==='ArrowRight'){{e.preventDefault();pick(Math.min((cur<0?-1:cur)+1,flows.length-1),0);}}
      else if(k==='ArrowUp'||k==='ArrowLeft'){{e.preventDefault();pick(Math.max((cur<0?flows.length:cur)-1,0),0);}}
      else if(k==='Home'){{e.preventDefault();pick(0,0);}}
      else if(k==='End'){{e.preventDefault();pick(flows.length-1,0);}}
      else if(k==='Escape'){{e.preventDefault();cur=-1;draw();}}
    }});
    prev.addEventListener('click',function(){{if(step>0){{step--;draw();}}}});
    next.addEventListener('click',function(){{if(cur>=0&&step<flows[cur].steps.length-1){{step++;draw();}}}});
    clear.addEventListener('click',function(){{cur=-1;draw();}});

    function fromHash(){{
      var m=/flow=([^&]+)(?:&step=(\\d+))?/.exec(location.hash||'');
      if(!m) return false;
      var id=decodeURIComponent(m[1]),k=-1;
      each(flows,function(f,j){{if(f.id===id)k=j;}});
      if(k<0) return false;                       /* unknown id: stay neutral */
      var s=Math.max(0,Math.min((parseInt(m[2],10)||1)-1,flows[k].steps.length-1));
      pick(k,s);
      return true;
    }}
    window.addEventListener('hashchange',fromHash);
    if(!fromHash()) draw();
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
    meta, body_md = parse_frontmatter(md_path.read_text(encoding="utf-8"))
    body = render_markdown(body_md)

    repo = meta.get("applies_to", md_path.parents[1].name)
    tags = "".join(f'<span class="tag">{html.escape(t)}</span>'
                   for t in meta.get("stage", "").split() if t)
    nav = "".join(
        f'<a href="#{m.group(1)}">{html.escape(re.sub("<[^>]+>", "", m.group(2)))}</a>'
        for m in re.finditer(r'<h2 id="([^"]+)">(.*?)</h2>', body)
    )
    # The page carries its own canonical link, so a copy that has been mailed
    # around or re-hosted still says where the live one lives.
    url = meta.get("published_url", "").strip()
    published = (f'<a href="{html.escape(url, quote=True)}">CANONICAL COPY</a>'
                 if url.startswith(("http://", "https://")) else "")

    return TEMPLATE.format(
        title=f"{repo} — Architecture",
        repo=html.escape(repo.upper()),
        accent=meta.get("accent", "#F5A623"),
        src_hash=_src_hash(md_path), gen_hash=_gen_hash(),
        tags=tags, nav=nav, body=body, published=published,
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
    rendered = html_path.read_text(encoding="utf-8")
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
    ap.add_argument("--publish", action="store_true",
                    help="after rendering, print the publish manifest line for "
                         "the agent to act on (this script never uploads)")
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

    # Strip per-line trailing whitespace. A generated artifact that trips a
    # repo's trailing-whitespace pre-commit hook cannot be committed at all: the
    # hook rewrites the staged copy, that conflicts with the working tree, and
    # the commit rolls back — in a loop. Cheap to emit clean; expensive to
    # diagnose at the commit.
    try:
        page = "\n".join(ln.rstrip() for ln in build(args.input).split("\n"))
    except ArchFlowError as exc:
        # A dangling flow reference is a content bug with a precise location, so
        # it gets a sentence rather than a traceback. Same exit code as a missing
        # input: the render did not happen and nothing was written.
        print(f"{args.input}: {exc}", file=sys.stderr)
        return 2
    args.output.write_text(page, encoding="utf-8")
    print(f"wrote {args.output}  ({args.output.stat().st_size:,} bytes)")

    if args.publish:
        meta, _ = parse_frontmatter(args.input.read_text(encoding="utf-8"))
        repo = meta.get("applies_to", args.input.parents[1].name)
        url = meta.get("published_url", "").strip()
        title = f'{repo} — Architecture'
        if url.startswith(("http://", "https://")):
            print(f'PUBLISH  {args.output}  url={url}  title="{title}"')
        else:
            # No address yet. Publishing mints one; writing it back into the
            # frontmatter is what stops the next render minting another.
            print(f'PUBLISH-NEW  {args.output}  title="{title}"')
    return 0


if __name__ == "__main__":
    sys.exit(main())
