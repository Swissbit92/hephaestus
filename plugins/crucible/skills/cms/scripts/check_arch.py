#!/usr/bin/env python3
"""Structural check on a rendered architecture page. The file is not done when
it is written — it is done when it passes this.

WHY THIS EXISTS: the layout engine in `render_arch.py` was only ever exercised on
two graphs its own author wrote. Layout engines do not fail loudly; they emit a
diagram where a connector runs through a box or two nodes sit on top of each
other, and it looks plausible until someone reads it carefully. At six repos
nobody reads all of them carefully.

It parses the **emitted SVG**, not the engine's intermediate geometry. That is
deliberate: the artifact is what ships, and checking the intermediate would miss
anything the rendering step gets wrong.

Checks, each with a stable ID so a failure is greppable:

    C1  node rects overlap
    C2  a connector passes through the interior of a node
    C3  geometry outside the viewBox
    C4  a group box does not contain its members with padding
    C5  degenerate geometry (zero/negative width or height)
    C6  a connector path is malformed or empty

    python3 tools/check_arch.py docs/ARCHITECTURE.html [more.html ...]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import NamedTuple

EPS = 0.5                    # sub-pixel touching is fine; overlap is not
GROUP_MIN_PAD = 4.0          # a group box must clear its members by at least this

RE_SVG = re.compile(r"<svg[^>]*viewBox=\"([^\"]+)\"[^>]*>(.*?)</svg>", re.S)
RE_RECT = re.compile(
    r'<rect class="(?P<cls>[^"]*)"[^>]*?x="(?P<x>[-\d.]+)"\s+y="(?P<y>[-\d.]+)"\s+'
    r'width="(?P<w>[-\d.]+)"\s+height="(?P<h>[-\d.]+)"'
)
RE_PATH = re.compile(r'<path class="(?P<cls>[^"]*)" d="(?P<d>[^"]*)"')
RE_COORD = re.compile(r"[ML]\s*([-\d.]+)\s+([-\d.]+)")


class Violation(NamedTuple):
    code: str
    detail: str


def _rects(svg: str):
    """Node and group rects, keyed by class. Ignores anything without geometry."""
    nodes, groups = [], []
    for m in RE_RECT.finditer(svg):
        box = (float(m["x"]), float(m["y"]), float(m["w"]), float(m["h"]))
        (groups if "grp" in m["cls"] else nodes).append(box)
    return nodes, groups


def _segments(d: str):
    """Orthogonal path -> list of ((x1,y1),(x2,y2)). Non-orthogonal segments are
    returned too; C2 handles them conservatively via their bounding box."""
    pts = [(float(a), float(b)) for a, b in RE_COORD.findall(d)]
    return [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)], pts


def _overlaps(a, b, eps=EPS) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return (ax + aw - eps > bx and bx + bw - eps > ax
            and ay + ah - eps > by and by + bh - eps > ay)


def _seg_enters(seg, rect) -> bool:
    """Does this segment pass through the rect's INTERIOR?

    Touching an edge is allowed — connectors legitimately start on a node's
    bottom border. Only strict penetration counts, which is why the comparison
    is against the inset rectangle rather than the rectangle itself.
    """
    (x1, y1), (x2, y2) = seg
    rx, ry, rw, rh = rect
    ix0, iy0 = rx + EPS, ry + EPS
    ix1, iy1 = rx + rw - EPS, ry + rh - EPS
    if ix1 <= ix0 or iy1 <= iy0:
        return False

    sx0, sx1 = sorted((x1, x2))
    sy0, sy1 = sorted((y1, y2))
    # Separating-axis on the segment's bounding box is exact for axis-aligned
    # segments and conservative (may over-report) for diagonals, which the
    # engine does not emit.
    return sx1 > ix0 and sx0 < ix1 and sy1 > iy0 and sy0 < iy1


def check_svg(svg_body: str, view_box: str) -> list:
    v = []
    vb = [float(t) for t in view_box.replace(",", " ").split()]
    _, _, vw, vh = vb
    nodes, groups = _rects(svg_body)

    for box in nodes + groups:
        if box[2] <= 0 or box[3] <= 0:
            v.append(Violation("C5", f"degenerate rect {box}"))

    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            if _overlaps(nodes[i], nodes[j]):
                v.append(Violation("C1", f"node {nodes[i]} overlaps {nodes[j]}"))

    for m in RE_PATH.finditer(svg_body):
        segs, pts = _segments(m["d"])
        if not pts:
            v.append(Violation("C6", f'empty path d="{m["d"][:60]}"'))
            continue
        for seg in segs:
            for nd in nodes:
                if _seg_enters(seg, nd):
                    v.append(Violation(
                        "C2", f"connector segment {seg} enters node {nd}"))
        for (px, py) in pts:
            if not (-EPS <= px <= vw + EPS and -EPS <= py <= vh + EPS):
                v.append(Violation("C3", f"path point ({px},{py}) outside viewBox {vw}x{vh}"))

    for box in nodes + groups:
        x, y, w, h = box
        if x < -EPS or y < -EPS or x + w > vw + EPS or y + h > vh + EPS:
            v.append(Violation("C3", f"rect {box} outside viewBox {vw}x{vh}"))

    # A group must enclose every node that visually sits inside it. Checking
    # containment-with-padding catches the class of bug where an ungrouped node
    # drifts into a boundary it is not a member of.
    for g in groups:
        inside = [n for n in nodes if _overlaps(n, g)]
        for n in inside:
            gx, gy, gw, gh = g
            nx, ny, nw, nh = n
            if not (nx >= gx + GROUP_MIN_PAD - EPS and ny >= gy + GROUP_MIN_PAD - EPS
                    and nx + nw <= gx + gw - GROUP_MIN_PAD + EPS
                    and ny + nh <= gy + gh - GROUP_MIN_PAD + EPS):
                v.append(Violation(
                    "C4", f"node {n} straddles group boundary {g} "
                          f"(needs {GROUP_MIN_PAD}px clearance)"))
    return v


def check_file(path: Path) -> tuple[list, int]:
    """Returns (violations, diagram_count).

    A page with no diagrams is not a failure — most repos have prose long before
    they have their first archview block, and flagging them would make this
    checker cry wolf on four of six repos. A false positive is how a checker
    gets switched off, which costs more than the check was worth. Only malformed
    SVG counts.
    """
    html = path.read_text(encoding="utf-8")
    found = RE_SVG.findall(html)
    if not found:
        if "<svg" in html:
            return [Violation("C6", "an <svg> is present but has no parseable viewBox")], 0
        return [], 0
    out = []
    for vb, body in found:
        out.extend(check_svg(body, vb))
    return out, len(found)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("-q", "--quiet", action="store_true", help="only report failures")
    args = ap.parse_args()

    bad = 0
    for f in args.files:
        if not f.exists():
            print(f"MISSING  {f}")
            bad += 1
            continue
        v, n_svg = check_file(f)
        if v:
            bad += 1
            print(f"FAIL  {f.name}  ({len(v)} violation{'s' if len(v) != 1 else ''})")
            for item in v[:12]:
                print(f"      [{item.code}] {item.detail}")
            if len(v) > 12:
                print(f"      ... and {len(v) - 12} more")
        elif not args.quiet:
            what = f"{n_svg} diagram{'s' if n_svg != 1 else ''}" if n_svg else "no diagrams"
            print(f"PASS  {f.name}  ({what}, 0 violations)")

    print(f"\n{bad}/{len(args.files)} file(s) with >=1 violation")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
