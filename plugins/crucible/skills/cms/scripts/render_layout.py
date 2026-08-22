#!/usr/bin/env python3
"""Diagram layout — pure geometry over (nodes, edges, groups). Pure stdlib.

Split out of `render.py`, where it was 178 lines of graph maths sitting between a markdown
parser and an SVG emitter. It knows nothing about HTML, markdown, CMS vocabulary or the
document being rendered: give it a node list and an edge list and it returns coordinates.
That independence is why this was the first seam worth cutting — there are no back-edges
to `render`, so the split is a move rather than an untangling.

Node order is load-bearing. Layering is longest-path over edges whose target appears
*later* in the node list; an edge pointing backwards is a back edge and is routed
differently. A caller that reorders nodes changes the picture.
"""
from __future__ import annotations

PAD_X, PAD_Y = 24, 30
CHAR_W = 6.5
MIN_W, MAX_W = 108, 215
def _lines(nd: dict) -> int:
    return 1 + bool(nd.get("sub")) + bool(nd.get("tech"))
def _node_w(nd: dict) -> float:
    """Width from the longest line. Tech strings run long, so they get a slightly
    tighter per-character budget rather than forcing every box wider."""
    longest = max(len(nd["label"]),
                  len(nd.get("sub", "")),
                  len(nd.get("tech", "")) * 0.86)
    return max(MIN_W, min(MAX_W, longest * CHAR_W + 24))

ROW_GAP = 60
COL_GAP = 30
NODE_H = {1: 40, 2: 54, 3: 66}

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
    """Straight across within a row, straight down at the wrap.

    Endpoints are rounded to whole pixels because the rects are emitted at zero
    decimal places and the paths at one: a node placed at x=201.5 renders as
    `202` while its right edge computes to 349.5, and the checker — reading only
    what shipped — correctly calls a connector starting there *inside the box*.
    The geometry was right and the rendering disagreed with it.
    """
    if abs(a["y"] - b["y"]) < 1:                       # same row, side by side
        x1 = round(a["x"] + a["w"]) + 1 if b["x"] > a["x"] else round(a["x"]) - 1
        x2 = round(b["x"]) - 5 if b["x"] > a["x"] else round(b["x"] + b["w"]) + 5
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
