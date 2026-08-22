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

    /cms render                     # docs/ARCHITECTURE.md -> .html (+ .txt)
    /cms render --check             # exit 1 if the page is stale
    /cms render --publish           # print the publish manifest line
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
from pathlib import Path

# Layout is pure geometry and lives in its own module now. Re-exported here because
# `render._layer` and friends are part of this module's surface as far as the test suite
# and `site.py` are concerned — the split is meant to be invisible to callers.
from render_layout import (  # noqa: F401,E402
    CHAR_W,
    COL_GAP,
    MAX_W,
    MIN_W,
    NODE_H,
    PAD_X,
    PAD_Y,
    ROW_GAP,
    _lines,
    _node_w,
    _adjacent_path,
    _chain_edge,
    _chain_order,
    _lane_path,
    _layer,
    _place,
    _place_chain,
)

# Paths resolve from the repo being rendered, never from this script's own
# location — the script lives in the plugin and the docs do not.


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


def _default_paths(repo: Path) -> tuple[Path, Path]:
    return repo / "docs" / "ARCHITECTURE.md", repo / "docs" / "ARCHITECTURE.html"


# Conventional documentation filenames, spelled the way a reader expects rather
# than the way the filesystem does. These are cross-industry conventions, not
# anyone's project vocabulary, so keeping the map here costs no neutrality.
DOC_TITLES = {
    "README": "Overview",
    "CHANGELOG": "Changelog",
    "SECURITY": "Security",
    "VISION": "Vision",
    "ARCHITECTURE": "Architecture",
    "ROADMAP": "Roadmap",
    "LESSONS_LEARNED": "Lessons learned",
    "THREAT_LEVEL": "Threat level",
    "DEPLOYMENT": "Deployment",
    "OPERATIONS": "Operations",
    "DEVELOPMENT": "Development",
    "TESTING": "Testing",
    "SAFETY": "Safety",
}


def _source_label(md_path: Path, repo: Path | None = None) -> str:
    """How the page names the file it was generated from.

    Repo-relative, so `SECURITY.md` and `docs/ROADMAP.md` read the way they are
    referred to in the repo. The footer exists so a reader who found the HTML can
    get back to the source; a path rooted on the build machine would defeat that.
    """
    if repo is not None:
        try:
            return md_path.resolve().relative_to(repo.resolve()).as_posix()
        except ValueError:
            pass
    parts = md_path.parts
    return "/".join(parts[-2:]) if len(parts) >= 2 else md_path.name


def _repo_name(md_path: Path, repo_root: Path | None) -> str:
    """Which repo this document belongs to.

    The caller knows; guessing from path depth does not survive a doc that lives
    at the repo root rather than under `docs/`, which silently named the *parent
    directory of the repo* instead.
    """
    if repo_root is not None:
        return repo_root.resolve().name
    return md_path.parents[1].name if len(md_path.parents) > 1 else md_path.stem


def _doc_title(md_path: Path, meta: dict) -> str:
    """What this document is called.

    Frontmatter wins, because the author wrote it. Files exempt from frontmatter
    — the conventional root ones — fall back to the map, and anything unrecognised
    falls back to a readable form of its own filename. The point is that no caller
    has to say what a document is; the document says.
    """
    title = (meta.get("title") or "").strip()
    if title:
        return title
    stem = md_path.stem.upper()
    return DOC_TITLES.get(stem, md_path.stem.replace("_", " ").replace("-", " ").title())

# ── layout constants ────────────────────────────────────────────────────────
# One engine serves both diagram types. A flow and a topology are the same
# problem — a layered DAG — and only their styling differs, so there is one
# layout implementation and two skins rather than two of everything.
ROW_GAP = 60
COL_GAP = 30
# Height by line count. A node carries up to three lines: what it is called, what
# it does, and what it is built from — the third being C4's convention that
# technology is an annotation on the container, not a separate view.
NODE_H = {1: 40, 2: 54, 3: 66}
GROUP_PAD = 18


# ════════════════════════════════════════════════════════════════════════════
# markdown subset
# ════════════════════════════════════════════════════════════════════════════

# Four states and no more. A vocabulary this small is one a reader learns once
# and an author cannot misuse; a fifth colour stops it meaning anything at a
# glance. Never colour alone — the label carries the meaning.
PILL_STATES = ("ok", "warn", "bad", "mute")
RE_PILL = re.compile(r"\[\[(ok|warn|bad|mute):([^\]|\n]+)\]\]")


def _inline(text: str) -> str:
    """Escape, then re-introduce the few inline forms an architecture doc uses.

    Deliberately small. A full markdown implementation is not the job, and every
    construct supported here is one more thing that can render wrong.
    """
    out = html.escape(text, quote=False)
    # Ahead of the code and emphasis passes, so a pill label cannot be
    # half-consumed by one of them and emitted as something else.
    out = RE_PILL.sub(
        lambda m: f'<span class="pill pill-{m.group(1)}">{m.group(2).strip()}</span>',
        out,
    )
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
    plot_index = 0
    # A flow step's note explains the very box it points at, and the archview is
    # emitted before the archflow below it is parsed — so the notes are gathered
    # in one cheap pre-pass rather than making the author write each sentence
    # twice. An explicit note on the node still wins.
    step_notes: dict[str, dict] = {}
    for fm in re.finditer(r"^```archflow\n(.*?)^```", md, re.S | re.M):
        try:
            fspec = json.loads(fm.group(1))
        except ValueError:
            continue
        bucket = step_notes.setdefault(fspec.get("view"), {})
        for fl in fspec.get("flows", []):
            for st in fl.get("steps", []):
                if st.get("node") and st.get("note"):
                    bucket.setdefault(st["node"], st["note"])
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
                vid = spec.get("id") or f"f{fig_index}"
                for nd in spec["nodes"]:
                    if not nd.get("note") and nd["id"] in step_notes.get(vid, {}):
                        nd["note"] = step_notes[vid][nd["id"]]
                views[vid] = {"fig": fig_index, "spec": spec}
                out.append(render_diagram(spec, fig_index))
            elif lang == "archstat":
                out.append(render_stats(json.loads(body)))
            elif lang == "archplot":
                plot_index += 1
                out.append(render_plot(json.loads(body), plot_index))
            elif lang == "archflow":
                out.append(render_flow(json.loads(body), views, claimed_flows))
            elif lang == "html":
                out.append(body)                       # the mechanism socket
            else:
                # The button is emitted here rather than injected on load, so
                # the block does not reflow after paint.
                out.append(
                    f'<div class="cb">'
                    f'<button class="cpy" type="button" data-copy>copy</button>'
                    f'<pre><code>{html.escape(body)}</code></pre></div>'
                )
            continue

        # h1 is consumed but not emitted — the page header already shows the repo
        # name, and a second <h1> would just repeat it.
        m = RE_HEAD.match(line)
        if m:
            lvl, txt = len(m.group(1)), m.group(2)
            if lvl > 1:
                # A heading may contain an inline link. The anchor has to come
                # from what the reader sees, not from the URL behind it —
                # otherwise a heading like "Track ([ADR-006](decisions/006-….md))"
                # produces an id with the whole filename inside it, and every
                # link written against the visible text misses.
                clean = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1",
                               re.sub(r"[*`]", "", txt.lower()))
                slug = re.sub(r"[^a-z0-9]+", "-", clean).strip("-")
                # A doc's own table of contents was written against GitHub's
                # slug rules, which drop an emoji but keep the hyphen that the
                # space beside it produced: "## 🎯 What next" is `#-what-next`
                # there and `#what-next` here. Emitting both means those links
                # land instead of silently doing nothing.
                # Deliberately not stripped: GitHub converts the space an emoji
                # left behind into a hyphen, which is the whole reason these
                # anchors start with one.
                gh = re.sub(r"[^a-z0-9 _-]", "", clean).replace(" ", "-")
                alias = (f'<span id="{gh}" class="anchor-alias"></span>'
                         if gh and gh != slug else "")
                out.append(f'{alias}<h{lvl} id="{slug}">{_inline(txt)}</h{lvl}>')
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


def _node_note(nd: dict) -> str:
    """The authored sentence, or an honest admission that there is not one.

    Deliberately NOT synthesized from the graph. Every tool that shows node
    detail — Ilograph, Structurizr, IcePanel, Backstage — takes this sentence
    from the author, because label + kind + a three-word subtitle is not enough
    signal to build one from, and a bad generated sentence is worse than a short
    honest gap. The relationship line below IS derived, because that is a
    traversal rather than a claim.
    """
    return nd.get("note") or ""


def _node_links(nd: dict, spec: dict) -> str:
    """Who feeds this and what it feeds — mechanical, so safe to generate."""
    label = {n["id"]: n["label"] for n in spec["nodes"]}
    edges = spec.get("edges", [])
    ins = [label.get(e["from"], e["from"]) for e in edges if e["to"] == nd["id"]]
    outs = [label.get(e["to"], e["to"]) for e in edges if e["from"] == nd["id"]]
    bits = []
    if ins:
        bits.append("← " + ", ".join(ins))
    if outs:
        bits.append("→ " + ", ".join(outs))
    return "   ".join(bits)








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
                 f'data-label="{html.escape(nd["label"], quote=True)}" '
                 f'data-sub="{html.escape(nd.get("sub", "") or "", quote=True)}" '
                 f'data-tech="{html.escape(nd.get("tech", "") or "", quote=True)}" '
                 f'data-note="{html.escape(_node_note(nd), quote=True)}" '
                 f'data-goto="{html.escape(nd.get("href", ""), quote=True)}" '
                 f'data-links="{html.escape(_node_links(nd, spec), quote=True)}" '
                 f'data-kind="{html.escape(KIND_MEANING.get(nd.get("kind", "module"), "component"), quote=True)}" '
                 f'tabindex="0" '
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
    # A readout on EVERY diagram, not only the ones a flow happens to walk.
    # "What is this box" is the question every diagram gets asked, and the model
    # already holds the answer — it was reaching only screen readers.
    # Inline below the figure, and the box reserves its height up front so
    # selecting a node does not shove the page down. Empty-state copy names the
    # three things you will get rather than announcing that nothing is selected.
    p.append(f'<div class="inspect" data-inspect="fig-f{fig}">'
             f'<span class="ins-hint">Click a box to see what it is, what it '
             f'does, and how it connects.</span>'
             f'<span class="ins-body" hidden aria-live="polite">'
             f'<span class="ins-head"><b class="ins-t"></b>'
             f'<span class="ins-k"></span><span class="ins-tech"></span></span>'
             f'<span class="ins-s"></span><span class="ins-links"></span><a class="ins-goto" hidden></a></span></div>')
    # A walker on every diagram. Where an archflow declares a path it walks that
    # path and says so; otherwise it tours the boxes in layout order and says
    # THAT. Labelling the difference is the point: a derived order presented as
    # a narrative is the same lie as a synthesized description, one level up.
    order = ",".join(g["nd"]["id"] for g in geo.values())
    p.append(f'<div class="tour" data-tour="fig-f{fig}" '
             f'data-order="{html.escape(order, quote=True)}">'
             f'<span class="tourlbl" data-tour-lbl>Tour<span class="tourwhy">'
             f' &middot; layout order</span></span>'
             f'<button class="pz" type="button" data-tour-prev disabled>&#8592; prev</button>'
             f'<span class="tourpos" data-tour-pos>&#8212;</span>'
             f'<button class="pz" type="button" data-tour-next>next &#8594;</button>'
             f'<button class="pz tourclear" type="button" data-tour-clear>clear</button>'
             f'</div>')
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
    # Fixed order — own code, then processes, then what they touch, then what is
    # outside the boundary. Following node-declaration order instead meant the
    # same legend reordered itself between diagrams on one page, so the reader
    # had to re-read it every time.
    present = {nd.get("kind", "module") for nd in nodes}
    used = [k for k in KIND_MEANING if k in present]
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


def render_stats(spec: list) -> str:
    """The gauge row: the handful of facts worth reading before the prose.

    The footer of this page claims STRUCTURE ONLY, NO RUNTIME STATE, and a row of
    gauges is exactly where that claim goes to die — "tests: 357" and "uptime:
    99.9%" are the two most tempting and most rotten things to put here. So a
    gauge takes a `value` the author wrote down and nothing is computed: if it is
    the sort of fact that changes without anyone editing this file, it does not
    belong in it. Prefer what is true because of a decision (venue, gating,
    allocation) over what is true because of a run.
    """
    if not isinstance(spec, list) or not spec:
        raise ArchStatError("archstat must be a non-empty list of gauges")
    cells = []
    for k, g in enumerate(spec, 1):
        if not g.get("label") or not g.get("value"):
            raise ArchStatError(
                f"gauge {k} needs both 'label' and 'value'; got {sorted(g)}"
            )
        state = g.get("state", "")
        if state and state not in PILL_STATES:
            raise ArchStatError(
                f"gauge {k} state {state!r} is not one of {list(PILL_STATES)}"
            )
        note = (f'<small>{html.escape(g["note"])}</small>'
                if g.get("note") else "")
        cells.append(
            f'<div class="gauge"{f" data-state={state}" if state else ""}>'
            f'<dt>{html.escape(g["label"])}</dt>'
            f'<dd>{html.escape(g["value"])}{note}</dd></div>'
        )
    return f'<dl class="gauges">{"".join(cells)}</dl>'


class ArchStatError(ValueError):
    """A gauge row that would render as a blank or a lie."""


class ArchPlotError(ValueError):
    """A plot that would mislead: unlabelled, unscaled, or synthetic-as-measured."""


PLOT_TONES = {"good": "--phos", "bad": "--red", "accent": "--accent",
              "ink": "--txt", "faint": "--edge2"}


def _plot_walk(gen: dict, n: int) -> list[float]:
    """A deterministic random walk from a seed.

    Deterministic because a figure that redraws differently on every render is
    a diff with no meaning. The seed is written in the document, so the picture
    is reproducible from its source like everything else on the page.
    """
    import random
    rng = random.Random(gen.get("seed", 0))
    vol, drift = float(gen.get("vol", 0.01)), float(gen.get("drift", 0.0))
    v, out = 0.0, []
    for _ in range(n):
        v += rng.gauss(drift, vol)
        out.append(v)
    # A hedged leg is the negation of the leg it hedges. Expressing that as a
    # flag over the same seed keeps the two lines exact mirrors — drawing them
    # from two seeds would let them drift apart and quietly stop being a hedge.
    return [-x for x in out] if gen.get("mirror") else out


def _plot_gate(vals: list[float], on: float, off: float) -> list[bool]:
    """Run a two-threshold gate over a series, exactly as the code under test
    would. The shaded spans are therefore derived from the drawn line rather
    than positioned by hand — the two cannot drift apart and quietly disagree.
    """
    out, cur = [], False
    for v in vals:
        if v > on:
            cur = True
        elif v < off:
            cur = False
        out.append(cur)
    return out


def render_plot(spec: dict, fig: int = 1) -> str:
    """A labelled line plot: the mechanism socket, without the hand-rolled SVG.

    Exists because the alternative is authoring raw SVG per figure, which costs
    the same effort every time and silently reintroduces the same three defects:
    end-labels clipped by the viewBox, a label sitting beside the wrong line
    because it was positioned by hand, and a tone that fails contrast. Those are
    layout problems, so the layout engine should own them, not the author.
    """
    series = spec.get("series") or []
    if not series:
        raise ArchPlotError("archplot needs at least one series")

    n = max((len(s["points"]) for s in series if s.get("points")), default=0) \
        or int(spec.get("samples", 120))
    generated = False
    for k, s in enumerate(series, 1):
        if not s.get("label"):
            raise ArchPlotError(f"series {k} has no label; an unlabelled line "
                                f"teaches nothing")
        if "points" not in s:
            if "walk" not in s and "ramp" not in s:
                raise ArchPlotError(
                    f"series {s['label']!r} has no 'points', 'walk' or 'ramp'")
            generated = True
            s["points"] = (_plot_walk(s["walk"], n) if "walk" in s else
                           [i / (n - 1) * float(s["ramp"]) for i in range(n)])
        tone = s.get("tone", "ink")
        if tone not in PLOT_TONES:
            raise ArchPlotError(f"series {s['label']!r} tone {tone!r} is not one "
                                f"of {sorted(PLOT_TONES)}")
    # The invariant worth having: a picture drawn from a seed must never be
    # readable as a measurement. Marking it is the author's call to make
    # explicitly, so the render refuses rather than guessing.
    if generated and not spec.get("schematic"):
        raise ArchPlotError(
            "this plot generates its own data, so it must set \"schematic\": true — "
            "a synthetic curve that reads as a measurement is the one failure mode "
            "of a figure like this")

    W = int(spec.get("width", 820))
    H = int(spec.get("height", 260))
    LEFT = 56
    # The gutter is measured from the longest label rather than guessed, which
    # is what stops the end-labels being clipped by the viewBox.
    labels = [s["label"] for s in series] + \
             [t.get("label", "") for t in spec.get("thresholds", [])]
    RIGHT = max(70, int(max((len(x) for x in labels), default=8) * 5.6) + 16)
    spans = spec.get("spans") or []
    # Span bars sit below the plot and the x-label sits below those. Reserving
    # for only one of the two is how the label ends up drawn across the bars.
    BOT = H - (46 if spans else 18)

    upper = [s for s in series if s.get("axis") == "upper"]
    main = [s for s in series if s.get("axis") != "upper"]
    top = 16
    ub = top + (H * 0.30 if upper else 0)
    mid = (ub + BOT) / 2

    def X(i: int) -> float:
        return LEFT + i * (W - LEFT - RIGHT) / max(n - 1, 1)

    lo = min((min(s["points"]) for s in main), default=-1.0)
    hi = max((max(s["points"]) for s in main), default=1.0)
    for t in spec.get("thresholds", []):
        lo, hi = min(lo, t["value"]), max(hi, t["value"])
    rng_ = (hi - lo) or 1.0
    pad = rng_ * 0.12

    def Y(v: float) -> float:
        return BOT - (v - lo + pad) / (rng_ + 2 * pad) * (BOT - ub)

    p = [f'<div class="figwrap"><svg id="fig-p{fig}" viewBox="0 0 {W} {H}" '
         f'width="{W}" height="{H}" role="img" aria-label='
         f'"{html.escape(spec.get("alt") or spec.get("caption", "plot"))}">']

    # Every label in the right-hand gutter — band, threshold, series end, span —
    # competes for the same column, so they are collected here and placed in one
    # pass at the end. Deconflicting only series against each other was a real
    # defect: a series endpoint landed on top of a threshold label and both
    # became unreadable.
    gutter: list[tuple[float, str, str]] = []

    for b in spec.get("bands", []):
        y0, y1 = Y(b["to"]), Y(b["from"])
        p.append(f'<rect x="{LEFT}" y="{y0:.1f}" width="{X(n-1)-LEFT:.1f}" '
                 f'height="{abs(y1-y0):.1f}" fill="var(--txt)" opacity=".05"/>')
        if b.get("label"):
            gutter.append(((y0 + y1) / 2, b["label"], "var(--faint)"))

    # Vertical marks: a moment on the x-axis rather than a level on the y-axis.
    # Some mechanisms are about *when* something happens, and a horizontal
    # threshold cannot say that.
    for k, mk in enumerate(spec.get("marks", [])):
        x = X(int(mk["at"]))
        col = f'var({PLOT_TONES[mk.get("tone", "faint")]})'
        p.append(f'<line x1="{x:.1f}" y1="{ub:.1f}" x2="{x:.1f}" y2="{BOT:.1f}" '
                 f'stroke="{col}" stroke-dasharray="3 3" opacity=".8"/>')
        if mk.get("label"):
            # Alternate the label baseline so two nearby marks do not collide.
            ly = ub - 4 + (10 if k % 2 else 0)
            anchor = "end" if x > W - RIGHT - 40 else "start"
            p.append(f'<text class="nds" x="{x + (-4 if anchor == "end" else 4):.1f}" '
                     f'y="{ly:.1f}" text-anchor="{anchor}" fill="{col}">'
                     f'{html.escape(mk["label"])}</text>')

    for t in spec.get("thresholds", []):
        y, col = Y(t["value"]), f'var({PLOT_TONES[t.get("tone", "faint")]})'
        p.append(f'<line x1="{LEFT}" y1="{y:.1f}" x2="{X(n-1):.1f}" y2="{y:.1f}" '
                 f'stroke="{col}" stroke-dasharray="5 4"/>')
        if t.get("label"):
            gutter.append((y, t["label"], col))

    if upper:
        ulo = min(min(s["points"]) for s in upper)
        uhi = max(max(s["points"]) for s in upper)
        urng = (uhi - ulo) or 1.0
        for s in upper:
            pts = " ".join(f"{X(i):.1f},{top + 8 + (1-(v-ulo)/urng)*(ub-top-18):.1f}"
                           for i, v in enumerate(s["points"]))
            p.append(f'<polyline fill="none" stroke="var({PLOT_TONES[s.get("tone","faint")]})" '
                     f'stroke-width="1.2" points="{pts}"/>')
            p.append(f'<text class="nds" x="{LEFT}" y="{top}">'
                     f'{html.escape(s["label"])}</text>')

    # Endpoint labels, nudged apart when two lines finish close together — the
    # label belongs to its own line, and overlapping text belongs to neither.
    for s in main:
        col = f'var({PLOT_TONES[s.get("tone", "ink")]})'
        pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(s["points"]))
        dash = ' stroke-dasharray="4 3"' if s.get("dash") else ""
        p.append(f'<polyline fill="none" stroke="{col}" stroke-width='
                 f'"{s.get("width", 1.4)}"{dash} points="{pts}"/>')
        gutter.append((Y(s["points"][-1]), s["label"], col))

    by_label = {s["label"]: s for s in series}
    for sp in spans:
        g, src = sp.get("gate") or {}, None
        src = by_label.get(g.get("series", ""))
        if not src:
            raise ArchPlotError(
                f"span {sp.get('label')!r} gates on series {g.get('series')!r}, "
                f"which is not one of {sorted(by_label)}")
        state = _plot_gate(src["points"], g["on"], g["off"])
        y, h = BOT + 12, 16
        i = 0
        while i < n:
            if state[i]:
                j = i
                while j + 1 < n and state[j + 1]:
                    j += 1
                p.append(f'<rect x="{X(i):.1f}" y="{y}" '
                         f'width="{max(X(j)-X(i), 2):.1f}" height="{h}" '
                         f'fill="var(--phos)" opacity=".3"/>')
                i = j + 1
            else:
                i += 1
        if sp.get("label"):
            gutter.append((y + h / 2, sp["label"], "var(--faint)"))

    placed: list[float] = []
    for y, text, col in sorted(gutter, key=lambda g: g[0]):
        while any(abs(y - q) < 11 for q in placed):
            y += 11
        placed.append(y)
        p.append(f'<text class="nds" x="{X(n-1)+8:.0f}" y="{y+3:.1f}" '
                 f'fill="{col}">{html.escape(text)}</text>')

    if spec.get("xlabel"):
        p.append(f'<text class="nds" x="{LEFT}" y="{H-5}">'
                 f'{html.escape(spec["xlabel"])}</text>')
    p.append("</svg>")
    cap = spec.get("caption", "")
    if spec.get("schematic"):
        cap = ('<span class="schem">schematic</span> ' + _inline(cap)) if cap \
            else '<span class="schem">schematic</span>'
    elif cap:
        cap = _inline(cap)
    if cap:
        p.append(f'<div class="figcap">{cap}</div>')
    p.append("</div>")
    return "".join(p)


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


# --- Theme assets -------------------------------------------------------------
# The page skeleton, stylesheet and scripts used to live here as a single 614-line Python
# string — 29% of this module, and the largest single thing in the repository. Nothing
# could lint it, highlight it, or diff it usefully, and every literal brace in the CSS and
# JS had to be doubled to survive `str.format` (514 of them).
#
# They are now real files under `assets/`, injected *after* formatting, so braces are
# literal again. `theme.css` keeps exactly one slot, `__ACCENT__`, substituted explicitly —
# a targeted replace rather than `.format`, so the stylesheet's own braces stay untouched.
# a targeted replace rather than `.format`, so the stylesheet's own braces stay untouched.
# The token is deliberately not `{accent}`: the sheet also *mentions* `{accent}` in a
# comment, and substituting both rewrote the comment. Caught by byte-comparing the
# rendered page, not by reading the diff.
ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"


def _asset(name: str) -> str:
    return (ASSETS_DIR / name).read_text(encoding="utf-8")


def _render_page(accent: str, **slots: str) -> str:
    """Format the shell first, inject the assets second. The order is load-bearing.

    `page.html` holds only the ten data slots and no literal braces, so it is safe to
    `.format`. The stylesheet and scripts are full of literal braces and must never reach
    the formatter — injecting them afterwards is what lets them stay unescaped on disk.
    Doing it the other way round raises KeyError on the first CSS rule.

    The output is one self-contained file by design: a rendered page gets mailed around and
    re-hosted, so it cannot depend on fetching a sibling stylesheet.
    """
    shell = _asset("page.html").format(**slots)
    return (shell
            .replace("<!--PREPAINT-->\n", _asset("prepaint.js"))
            .replace("<!--CSS-->\n", _asset("theme.css").replace("__ACCENT__", accent))
            .replace("<!--APPJS-->\n", _asset("app.js")))



SRC_HASH_RE = re.compile(r'<meta name="source-sha256" content="([0-9a-f]{64})">')
GEN_HASH_RE = re.compile(r'<meta name="renderer-sha256" content="([0-9a-f]{64})">')


def _src_hash(md_path: Path) -> str:
    return hashlib.sha256(md_path.read_bytes()).hexdigest()


def _gen_hash() -> str:
    """Hash of the whole renderer — this module *and* every theme asset.

    The source hash alone is not enough: change the renderer and every previously-generated
    page is stale while its source is untouched. On one repo that is a nuisance; across six
    it is six pages silently disagreeing with the tool that claims to produce them.

    It used to hash `Path(__file__)` alone, which was correct only while the stylesheet and
    scripts lived inside this file. The moment they moved to `assets/` that became the
    quietest possible bug: edit the CSS, and every page keeps reporting itself current
    while looking different — and the entire test suite still passes, because nothing tests
    what the hash *covers*. So the hash follows the assets rather than the module.

    Sorted by name, and the name is hashed alongside the bytes: without that, renaming an
    asset or swapping two files' contents leaves the digest unchanged.
    """
    h = hashlib.sha256()
    for part in _renderer_parts():
        h.update(part.name.encode("utf-8"))
        h.update(part.read_bytes())
    return h.hexdigest()


def _renderer_parts() -> list:
    """Every file whose contents can change what a rendered page looks like.

    Enumerated rather than assumed, and sorted, so the digest is stable across platforms.
    Anything added to the renderer must be added here — that is the one manual step the
    split introduced, and `test_every_renderer_module_is_in_the_hash` exists to catch a
    module that gets written and forgotten.
    """
    here = Path(__file__).resolve().parent
    modules = [here / "render.py", here / "render_layout.py"]
    assets = sorted(a for a in ASSETS_DIR.glob("*") if a.is_file())
    return [p for p in modules if p.is_file()] + assets


def build(md_path: Path, repo_root: Path | None = None,
          sitenav: str = "") -> str:
    meta, body_md = parse_frontmatter(md_path.read_text(encoding="utf-8"))
    body = render_markdown(body_md)

    repo = meta.get("applies_to") or _repo_name(md_path, repo_root)
    doc_title = _doc_title(md_path, meta)
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

    # `accent` is applied while inlining the stylesheet, not here: it is the one slot that
    # lives inside the CSS, and routing it through `.format` would require re-doubling
    # every literal brace in the sheet — the exact burden this extraction removed.
    return _render_page(
        meta.get("accent", "#F5A623"),
        title=f"{repo} — {doc_title}",
        source_label=html.escape(_source_label(md_path, repo_root).upper()),
        repo=html.escape(repo.upper()),
        src_hash=_src_hash(md_path), gen_hash=_gen_hash(),
        tags=tags, nav=nav, body=body, published=published,
        sitenav=sitenav,
    )


def build_text(md_path: Path, repo_root: Path | None = None) -> str:
    """The same document as flat prose, for the reader that is not a person.

    Docs now have two audiences and the second one parses badly: an agent handed
    the rendered page has to wade through 40KB of CSS and SVG coordinates to
    reach three sentences of meaning. The markdown is already the right artifact
    — this only strips the parts that are structure rather than content, so the
    text output cannot drift from the page beside it.
    """
    meta, body = parse_frontmatter(md_path.read_text(encoding="utf-8"))
    repo = meta.get("applies_to") or _repo_name(md_path, repo_root)

    out, i, lines = [], 0, body.split("\n")
    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            lang = line[3:].strip()
            i += 1
            buf = []
            while i < len(lines) and not lines[i].startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            if lang == "archview":
                # A diagram is a graph, and the graph reads better as sentences
                # than as the JSON that drew it.
                try:
                    spec = json.loads("\n".join(buf))
                except ValueError:
                    continue
                label = {nd["id"]: nd["label"] for nd in spec["nodes"]}
                out.append(f'[diagram] {spec.get("caption", "")}'.rstrip())
                for nd in spec["nodes"]:
                    bits = [nd["label"]]
                    if nd.get("sub"):
                        bits.append(nd["sub"])
                    out.append(f'  - {" — ".join(bits)}'
                               f' ({KIND_MEANING.get(nd.get("kind", "module"), "component")})')
                for e in spec.get("edges", []):
                    lbl = f' [{e["label"]}]' if e.get("label") else ""
                    out.append(f'  - {label.get(e["from"], e["from"])} ->'
                               f' {label.get(e["to"], e["to"])}{lbl}')
            elif lang == "archflow":
                try:
                    spec = json.loads("\n".join(buf))
                except ValueError:
                    continue
                for fl in spec.get("flows", []):
                    out.append(f'[flow] {fl.get("label", fl.get("id", ""))}')
                    for k, st in enumerate(fl.get("steps", []), 1):
                        what = st.get("node") or " -> ".join(st.get("edge", []))
                        note = f' — {st["note"]}' if st.get("note") else ""
                        out.append(f"  {k}. {what}{note}")
            elif lang == "archplot":
                # A picture is the one thing this file cannot carry, so it
                # carries what the picture asserts instead.
                try:
                    spec = json.loads("\n".join(buf))
                except ValueError:
                    continue
                kind = "schematic" if spec.get("schematic") else "plot"
                out.append(f'[{kind}] {spec.get("caption", "")}'.rstrip())
                for s in spec.get("series", []):
                    out.append(f'  - line: {s["label"]}')
                for t in spec.get("thresholds", []):
                    out.append(f'  - threshold: {t.get("label", t["value"])}'
                               f' at {t["value"]}')
                for b in spec.get("bands", []):
                    out.append(f'  - band {b["from"]} to {b["to"]}'
                               f'{": " + b["label"] if b.get("label") else ""}')
                for sp in spec.get("spans", []):
                    g = sp.get("gate") or {}
                    out.append(f'  - shaded where {g.get("series")} is gated on'
                               f' (on above {g.get("on")}, off below {g.get("off")}):'
                               f' {sp.get("label", "")}')
            elif lang == "archstat":
                try:
                    spec = json.loads("\n".join(buf))
                except ValueError:
                    continue
                for g in spec:
                    note = f' ({g["note"]})' if g.get("note") else ""
                    out.append(f'  - {g["label"]}: {g["value"]}{note}')
            elif lang == "html":
                continue                      # presentation only, no content
            else:
                out.append("\n".join(buf))
            out.append("")
            continue
        out.append(line)
        i += 1

    head = (f"# {repo} — {_doc_title(md_path, meta)}\n\n"
            f"Generated from {_source_label(md_path, repo_root)}. The rendered page is the "
            f"same content with diagrams; this is the text of it.\n")
    text = "\n".join(out)
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return head + "\n" + text.strip() + "\n"


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
        page = "\n".join(ln.rstrip() for ln in
                         build(args.input, args.repo.resolve()).split("\n"))
    except ArchFlowError as exc:
        # A dangling flow reference is a content bug with a precise location, so
        # it gets a sentence rather than a traceback. Same exit code as a missing
        # input: the render did not happen and nothing was written.
        print(f"{args.input}: {exc}", file=sys.stderr)
        return 2
    args.output.write_text(page, encoding="utf-8")
    print(f"wrote {args.output}  ({args.output.stat().st_size:,} bytes)")

    txt = args.output.with_suffix(".txt")
    txt.write_text(build_text(args.input, args.repo.resolve()), encoding="utf-8")
    print(f"wrote {txt}  ({txt.stat().st_size:,} bytes)")

    if args.publish:
        meta, _ = parse_frontmatter(args.input.read_text(encoding="utf-8"))
        repo = meta.get("applies_to") or _repo_name(args.input, args.repo.resolve())
        url = meta.get("published_url", "").strip()
        title = f'{repo} — {_doc_title(args.input, meta)}'
        if url.startswith(("http://", "https://")):
            print(f'PUBLISH  {args.output}  url={url}  title="{title}"')
        else:
            # No address yet. Publishing mints one; writing it back into the
            # frontmatter is what stops the next render minting another.
            print(f'PUBLISH-NEW  {args.output}  title="{title}"')
    return 0


if __name__ == "__main__":
    _utf8_stdio()
    sys.exit(main())
