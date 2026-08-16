#!/usr/bin/env python3
"""Build a multi-repo documentation site from the markdown already in the repos.

    site.py [root] [-c site.toml] [-o _site]

Nothing here authors content. Every page is markdown that already exists next to
the code it describes; this only decides which files become which page, renders
them through the same engine the standalone pages use, and links them together.

The rule that makes it work across repos without per-repo configuration:
**a page exists if its sources exist.** A repo with no DEPLOYMENT.md has no
"Running it" page and no dead link pointing at one. Adding the file later is the
whole of the work needed to make the page appear. No manifest to update, no
special-casing, and — the part that matters — no way for the nav to promise a
page that was never written.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import sys
from pathlib import Path

# `tomllib` is 3.11+, and this module is imported by the cms test suite on the declared
# floor (3.9). A top-level import here made the module unimportable there, which does not
# degrade one feature — it stops pytest collecting. It is imported in `main()` instead, at
# the one place a site.toml is actually read.

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render  # noqa: E402


# One page can draw on several files. `Security` is the clearest case: the
# posture and the rating are separate documents because they are reviewed on
# different cadences, but a reader wants them together.
DEFAULT_PAGES: list[dict] = [
    {"slug": "index",        "title": "Overview",
     "sources": ["README.md", "VISION.md"]},
    {"slug": "architecture", "title": "Architecture",
     "sources": ["docs/ARCHITECTURE.md"]},
    {"slug": "roadmap",      "title": "Roadmap",
     "sources": ["docs/ROADMAP.md"]},
    {"slug": "decisions",    "title": "Decisions",
     "sources": ["docs/decisions/*.md"]},
    {"slug": "lessons",      "title": "Lessons",
     "sources": ["docs/LESSONS_LEARNED.md"]},
    {"slug": "security",     "title": "Security",
     "sources": ["SECURITY.md", "docs/THREAT_LEVEL.md"]},
    {"slug": "running",      "title": "Running it",
     "sources": ["docs/DEPLOYMENT.md", "docs/OPERATIONS.md", "docs/SAFETY.md",
                 "docs/TESTING.md", "docs/DEVELOPMENT.md"]},
    {"slug": "changelog",    "title": "Changelog",
     "sources": ["CHANGELOG.md"]},
]


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


class SiteError(ValueError):
    """A site that could not be built, with a reason worth reading."""


def resolve_sources(repo: Path, patterns: list[str]) -> list[Path]:
    """Which of a page's candidate sources actually exist, in declared order.

    Globs sort by name so a numbered ADR sequence renders in its own order
    rather than the filesystem's.
    """
    found: list[Path] = []
    for pat in patterns:
        if "*" in pat:
            found.extend(sorted(repo.glob(pat)))
        elif (repo / pat).is_file():
            found.append(repo / pat)
    return found


def _strip_leading_h1(body: str) -> str:
    """Drop a document's own top-level heading.

    The merged page supplies the section title itself, so keeping the source's
    `# Security` produces the heading twice — once from the merge and once from
    the document — and the in-page nav lists both.
    """
    lines = body.split("\n")
    for i, ln in enumerate(lines):
        if not ln.strip():
            continue
        if ln.startswith("# "):
            return "\n".join(lines[i + 1:])
        break
    return body


def _demote(body: str) -> str:
    """Push every heading down one level.

    A merged page owns its own `#`; the parts it is made of each brought their
    own, and two `##  Security` blocks with no parent read as one flat document
    rather than two.
    """
    out = []
    fence = False
    for ln in body.split("\n"):
        if ln.startswith("```"):
            fence = not fence
        if not fence and ln.startswith("#") and not ln.startswith("######"):
            ln = "#" + ln
        out.append(ln)
    return "\n".join(out)


def merge_sources(paths: list[Path], repo: Path) -> str:
    """Concatenate several documents into the markdown for one page."""
    if len(paths) == 1:
        return paths[0].read_text(encoding="utf-8")

    chunks = []
    for pth in paths:
        meta, body = render.parse_frontmatter(pth.read_text(encoding="utf-8"))
        title = render._doc_title(pth, meta)
        rel = render._source_label(pth, repo)
        inner = _demote(_strip_leading_h1(body)).strip()
        chunks.append(f"## {title}\n\n*From `{rel}`.*\n\n{inner}\n")
    # The merged document keeps no frontmatter of its own: it has more than one
    # review date and more than one applies_to, and inventing a single value for
    # either would be a claim nobody made.
    return "\n\n".join(chunks)


RE_MD_LINK = re.compile(r'\[([^\]]*)\]\(([^)\s]+)(?:\s+"[^"]*")?\)')


def rewrite_links(md: str, src: Path, linkmap: dict[Path, str], here: str) -> str:
    """Point in-repo relative links at the pages they became.

    Markdown written next to code links the way the repo is laid out — a
    sibling repo's `../other-repo/docs/ROADMAP.md`, or a config file that is not
    a document at all. None of those paths exist in the built site.

    A link that maps to a page is rewritten. A link that maps to nothing is
    **unwrapped to plain text**, keeping the words and dropping the href, because
    a dead link tells the reader something is there when nothing is. The text
    still names the file, so nothing is lost but the false promise.
    """
    def sub(m):
        text, target = m.group(1), m.group(2)
        if target.startswith(("http://", "https://", "mailto:", "#")):
            return m.group(0)
        path, _, frag = target.partition("#")
        if not path:
            return m.group(0)
        try:
            resolved = (src.parent / path).resolve()
        except (OSError, ValueError):
            return f"{text}"
        dest = linkmap.get(resolved)
        if dest:
            rel = _relpath(here, dest)
            return f"[{text}]({rel}{'#' + frag if frag else ''})"
        return text
    return RE_MD_LINK.sub(sub, md)


def _relpath(here: str, dest: str) -> str:
    """A site-root-relative destination, expressed relative to the page using it."""
    from posixpath import relpath as _rp
    from posixpath import dirname
    return _rp(dest, dirname(here) or ".")


def build_linkmap(repos: list[dict]) -> dict[Path, str]:
    """Every source document -> the site page it ended up on."""
    m: dict[Path, str] = {}
    for r in repos:
        for pg in r["pages"]:
            url = f'{r["slug"]}/{pg["slug"]}.html'
            for q in pg.get("paths", []):
                m.setdefault(q.resolve(), url)
    return m



# ── search ──────────────────────────────────────────────────────────────────
# The index is inlined into one page rather than fetched. A fetch would be
# simpler, but it would also be the only thing on this site that needs a server
# to behave a particular way, and every other page works from a file:// URL. One
# page carrying the weight keeps that property for the other 165.

RE_FENCE_BLOCK = re.compile(r"```.*?```", re.S)
RE_MD_MARKUP = re.compile(r"[*_`#>|\[\]()]")


def _plain_text(md: str, limit: int = 4000) -> str:
    """Markdown reduced to searchable words."""
    meta_stripped = render.parse_frontmatter(md)[1]
    body = RE_FENCE_BLOCK.sub(" ", meta_stripped)
    body = RE_MD_LINK.sub(r"\1", body)
    body = RE_MD_MARKUP.sub(" ", body)
    return " ".join(body.split())[:limit]


def build_search_index(repos: list[dict]) -> list[dict]:
    idx = []
    for r in repos:
        for pg in r["pages"]:
            if not pg.get("paths"):
                continue
            texts, heads = [], []
            for q in pg["paths"]:
                raw = q.read_text(encoding="utf-8", errors="replace")
                texts.append(_plain_text(raw))
                heads += [h.strip() for h in
                          re.findall(r"^#{2,4}\s+(.+)$", raw, re.M)][:40]
            idx.append({"u": f'{r["slug"]}/{pg["slug"]}.html', "r": r["name"],
                        "t": pg["title"], "h": heads[:40],
                        "b": " ".join(texts)[:6000]})
    return idx


SEARCH_JS = r"""
var IDX = __INDEX__;
function esc(s){return s.replace(/[&<>]/g,function(c){
  return {'&':'&amp;','<':'&lt;','>':'&gt;'}[c];});}
/* Highlighting walks the string instead of building a RegExp from the query:
   a pattern compiled out of whatever the reader typed has to escape every
   metacharacter correctly, and getting that subtly wrong is how a search box
   starts throwing on a bracket. */
function mark(text, terms){
  var low = text.toLowerCase(), out = '', i = 0;
  while (i < text.length) {
    var best = -1, blen = 0;
    for (var j = 0; j < terms.length; j++) {
      var at = low.indexOf(terms[j], i);
      if (at >= 0 && (best < 0 || at < best)) { best = at; blen = terms[j].length; }
    }
    if (best < 0) { out += esc(text.slice(i)); break; }
    out += esc(text.slice(i, best)) + '<mark>' + esc(text.substr(best, blen)) + '</mark>';
    i = best + blen;
  }
  return out;
}
function run(q){
  var box = document.getElementById('sr');
  q = (q || '').trim().toLowerCase();
  if (q.length < 2) { box.innerHTML = '<p class="hint">Type at least two characters.</p>'; return; }
  var terms = q.split(/\s+/), out = [];
  for (var i = 0; i < IDX.length; i++) {
    var d = IDX[i];
    var head = (d.t + ' ' + d.r + ' ' + d.h.join(' ')).toLowerCase();
    var hay = head + ' ' + d.b.toLowerCase();
    var score = 0, ok = true;
    for (var j = 0; j < terms.length; j++) {
      var n = hay.split(terms[j]).length - 1;
      if (!n) { ok = false; break; }
      score += n;
      if (head.indexOf(terms[j]) >= 0) score += 40;
    }
    if (!ok) continue;
    var at = d.b.toLowerCase().indexOf(terms[0]);
    var frag = at < 0 ? d.b.slice(0, 200)
                      : d.b.slice(Math.max(0, at - 90), at + 150);
    out.push({ d: d, s: score, f: frag });
  }
  out.sort(function(a, b){ return b.s - a.s; });
  if (!out.length) { box.innerHTML = '<p class="hint">Nothing matched.</p>'; return; }
  var h = '<p class="hint">' + out.length + ' page' + (out.length > 1 ? 's' : '') + '.</p>';
  for (var k = 0; k < Math.min(out.length, 60); k++) {
    var o = out[k];
    h += '<article class="hit"><a href="' + o.d.u + '">' + esc(o.d.t) + '</a>' +
         ' <span class="in">' + esc(o.d.r) + '</span>' +
         '<p>' + mark(o.f, terms) + '…</p></article>';
  }
  box.innerHTML = h;
}
var inp = document.getElementById('sq');
inp.addEventListener('input', function(){ run(inp.value); });
var q0 = new URLSearchParams(location.search).get('q');
if (q0) { inp.value = q0; run(q0); }
inp.focus();
"""

SEARCH_CSS = """
#sq{width:100%;padding:.6rem .7rem;font:inherit;font-size:1rem;
  background:var(--panel);color:var(--txt);border:1px solid var(--edge2)}
#sq:focus{outline:2px solid var(--accent);outline-offset:-1px}
.hit{border-bottom:1px solid var(--edge);padding:.6rem 0}
.hit a{color:var(--accent);text-decoration:none;font-size:.95rem}
.hit .in{color:var(--faint);font-size:.68rem;letter-spacing:.06em;
  text-transform:uppercase;margin-left:.4rem}
.hit p{margin:.25rem 0 0;color:var(--mid);font-size:.8rem;line-height:1.55}
.hit mark{background:var(--accent);color:#12201C;padding:0 .1em}
.hint{color:var(--faint);font-size:.8rem}
"""


def render_search_page(repos: list[dict], cfg: dict) -> str:
    idx = build_search_index(repos)
    body = ('<h2 id="search">Search</h2>'
            '<p>Every document in every repository, including the reference '
            'material that no named section claims.</p>'
            '<input id="sq" type="search" autocomplete="off" spellcheck="false" '
            'placeholder="Search all documents…" aria-label="Search all documents">'
            '<div id="sr"></div>')
    page = render.TEMPLATE.format(
        title=f'{cfg.get("title", "Documentation")} — Search',
        repo=html.escape(cfg.get("title", "Documentation").upper()),
        accent=cfg.get("accent", "#F5A623"), src_hash="-",
        gen_hash=render._gen_hash(), tags="", nav="", body=body,
        published="", source_label="EVERY DOCUMENT IN THE SITE",
        sitenav=build_root_nav(repos, "search"))
    payload = json.dumps(idx, separators=(",", ":"))
    return (page.replace("</style>", SEARCH_CSS + "</style>", 1)
                .replace("</body>", "", 1)
            + "<script>" + SEARCH_JS.replace("__INDEX__", payload) + "</script>")


RE_ARCHVIEW = re.compile(r"^```archview\n(.*?)^```", re.S | re.M)


def link_repo_nodes(md: str, repos: list[dict], self_slug: str, here: str) -> str:
    """Give a diagram node that names another repo somewhere to go.

    Topology diagrams name their neighbours — the executor that reads these
    signals, the pipeline that writes this data — and in a single-page render
    those nodes were necessarily dead ends. In a site they do not have to be.

    Matching is on the node's exact label against a configured repo name, which
    is deliberately strict: a node whose label *is* a sibling repo's name is that
    repo, and anything looser would start inventing links.
    """
    by_name = {r["name"].lower(): r["slug"] for r in repos if r["slug"] != self_slug}
    if not by_name:
        return md

    def sub(m):
        try:
            spec = json.loads(m.group(1))
        except ValueError:
            return m.group(0)
        touched = False
        for nd in spec.get("nodes", []):
            slug = by_name.get(str(nd.get("label", "")).strip().lower())
            if slug and "href" not in nd:
                nd["href"] = _relpath(here, f"{slug}/index.html")
                touched = True
        if not touched:
            return m.group(0)
        return "```archview\n" + json.dumps(spec, indent=2, ensure_ascii=False) + "\n```"

    return RE_ARCHVIEW.sub(sub, md)


def build_nav(repos: list[dict], repo_slug: str, page_slug: str) -> str:
    """The two rows above every page: which repo, and which page within it."""
    def repo_link(r: dict) -> str:
        here = r["slug"] == repo_slug
        href = "index.html" if here else f"../{r['slug']}/index.html"
        cls = ' class="on"' if here else ""
        return f'<a href="{href}"{cls}>{html.escape(r["name"])}</a>'

    current = next(r for r in repos if r["slug"] == repo_slug)
    # Named sections only. The reference documents reach double figures in a
    # research-heavy repo, and a nav row listing every one of them stops being a
    # nav; their index page is the entry point instead.
    listed = [p for p in current["pages"] if not p.get("reference")]
    on_ref = any(p["slug"] == page_slug and p.get("reference")
                 for p in current["pages"])
    def page_link(p):
        # The class is bound before the f-string, not inlined into it: a backslash
        # inside an f-string expression is a SyntaxError before Python 3.12, and the
        # declared floor is 3.9. Same shape as repo_link above.
        here = p["slug"] == page_slug or (on_ref and p["slug"] == "reference")
        cls = ' class="on"' if here else ""
        return f'<a href="{p["slug"]}.html"{cls}>{html.escape(p["title"])}</a>'

    pages = "".join(page_link(p) for p in listed)
    return (
        '<div class="snav">'
        '<div class="grp"><a class="home" href="../index.html">&#9670; ALL</a>'
        '<a class="find" href="../search.html">&#9906; SEARCH</a>'
        + "".join(repo_link(r) for r in repos) + "</div>"
        f'<div class="grp"><span class="lbl">in {html.escape(current["name"])}</span>{pages}</div>'
        "</div>"
    )


def _slugify(name: str) -> str:
    out = "".join(c if c.isalnum() else "-" for c in name.lower())
    return "-".join(filter(None, out.split("-")))


def collect_reference(repo: Path, claimed: set[Path]) -> list[dict]:
    """Every doc under docs/ that no named page already covers.

    Without this the site is a curated subset, and every link in the prose that
    points at one of the uncovered files is dead. A research-heavy repo is mostly
    these — dated findings can outnumber the named sections ten to one — so
    leaving them out makes the site look complete while quietly dropping most of
    the corpus.
    """
    docs = repo / "docs"
    if not docs.is_dir():
        return []
    out = []
    for md in sorted(docs.rglob("*.md")):
        if md in claimed or "archive" in md.relative_to(docs).parts:
            continue
        # The slug carries the path, not just the filename: `docs/README.md`
        # and `docs/lore/README.md` are different documents, and naming both
        # `ref-readme` made one silently overwrite the other on disk.
        rel = md.relative_to(docs).with_suffix("")
        out.append({"slug": f"ref-{_slugify(rel.as_posix())}",
                    "title": " / ".join(rel.parts).replace("_", " "),
                    "sources": [], "paths": [md], "reference": True})
    return out


def build_root_nav(repos: list[dict], here: str) -> str:
    """The nav for the two pages that live at the site root.

    Same bar as everywhere else, minus the `../` — the home and search pages sit
    a directory above the repos rather than inside one.
    """
    links = "".join(
        f'<a href="{r["slug"]}/index.html">{html.escape(r["name"])}</a>'
        for r in repos)
    find = ('<a class="find on" href="search.html">&#9906; SEARCH</a>'
            if here == "search"
            else '<a class="find" href="search.html">&#9906; SEARCH</a>')
    home = ('<a class="home on" href="index.html">&#9670; ALL</a>' if here == "home"
            else '<a class="home" href="index.html">&#9670; ALL</a>')
    return f'<div class="snav"><div class="grp">{home}{find}{links}</div></div>'


def discover(root: Path, cfg: dict) -> list[dict]:
    """Work out what the site contains, before rendering any of it."""
    page_specs = cfg.get("pages", DEFAULT_PAGES)
    repos: list[dict] = []
    for entry in cfg.get("repos", []):
        path = (root / entry["path"]).resolve()
        if not path.is_dir():
            raise SiteError(f"repo path does not exist: {entry['path']}")
        slug = entry.get("slug") or path.name.lower().replace("_", "-")
        specs = list(page_specs) + list(entry.get("extra_pages", []))
        pages = []
        for spec in specs:
            srcs = resolve_sources(path, spec["sources"])
            if srcs:
                pages.append({**spec, "paths": srcs})
        claimed = {q for pg in pages for q in pg["paths"]}
        refs = collect_reference(path, claimed)
        if refs:
            pages.append({"slug": "reference", "title": "Reference",
                          "sources": [], "paths": [], "index_of": refs})
            pages.extend(refs)
        if not pages:
            raise SiteError(f"{entry['path']} has no renderable documents")
        seen: dict[str, str] = {}
        for pg in pages:
            src = ", ".join(str(q) for q in pg.get("paths", [])) or "(generated)"
            if pg["slug"] in seen:
                raise SiteError(
                    f'{entry["path"]}: two pages both want "{pg["slug"]}.html" — '
                    f'{seen[pg["slug"]]} and {src}. One would overwrite the other '
                    f'and the site would look complete without it.')
            seen[pg["slug"]] = src
        repos.append({"name": entry.get("name", path.name), "slug": slug,
                      "path": path, "pages": pages,
                      "blurb": entry.get("blurb", "")})
    if not repos:
        raise SiteError("no repos configured — nothing to build")
    return repos


def render_home(repos: list[dict], cfg: dict) -> str:
    """The one page that is written by the builder rather than by a repo.

    It is a directory, not a summary: it says what exists and links to it. Any
    prose here would be a second place to keep the ecosystem description current,
    and the ecosystem already has one.
    """
    cards = []
    for r in repos:
        links = " · ".join(
            f'<a href="{r["slug"]}/{p["slug"]}.html">{html.escape(p["title"])}</a>'
            for p in r["pages"])
        blurb = f'<p class="blurb">{html.escape(r["blurb"])}</p>' if r["blurb"] else ""
        cards.append(
            f'<section class="card"><h2><a href="{r["slug"]}/index.html">'
            f'{html.escape(r["name"])}</a></h2>{blurb}'
            f'<p class="links">{links}</p></section>')

    body = (f'<h2 id="repositories">Repositories</h2>\n'
            f'<div class="cards">{"".join(cards)}</div>')
    # Real destinations, not in-page anchors: this page has one heading, so
    # anchor links would have pointed at ids that are never emitted.
    nav = "".join(f'<a href="{r["slug"]}/index.html">{html.escape(r["name"])}</a>'
                  for r in repos)
    page = render.TEMPLATE.format(
        title=cfg.get("title", "Documentation"),
        repo=html.escape(cfg.get("title", "Documentation").upper()),
        accent=cfg.get("accent", "#F5A623"),
        src_hash="-", gen_hash=render._gen_hash(),
        tags="", nav=nav, body=body, published="",
        source_label="SITE.TOML",
        sitenav=build_root_nav(repos, "home"),
    )
    return page.replace("</style>", HOME_CSS + "</style>", 1)


HOME_CSS = """
.cards{display:grid;gap:.9rem;grid-template-columns:repeat(auto-fill,minmax(19rem,1fr))}
.card{border:1px solid var(--edge);background:var(--panel);padding:.9rem 1rem}
.card h2{margin:0 0 .3rem;font-size:1rem;border:0;padding:0}
.card h2 a{color:var(--accent);text-decoration:none}
.card .blurb{margin:.2rem 0 .5rem;color:var(--mid);font-size:.82rem}
.card .links{margin:0;font-size:.7rem;line-height:1.9;color:var(--faint)}
.card .links a{color:var(--faint);text-decoration:none;border-bottom:1px solid var(--edge)}
.card .links a:hover{color:var(--txt)}
.findbar{margin:0 0 1rem}
.findbar a{color:var(--accent);text-decoration:none;font-size:.8rem;
  letter-spacing:.04em;border-bottom:1px solid var(--edge2)}
"""


def render_reference_index(r: dict, pg: dict, nav: str) -> str:
    """A contents page for the documents no named page claimed."""
    rows = "".join(
        f'<tr><td><a href="{c["slug"]}.html">{html.escape(c["title"])}</a></td>'
        f'<td><code>{html.escape(render._source_label(c["paths"][0], r["path"]))}</code></td></tr>'
        for c in pg["index_of"])
    body = (f'<h2 id="reference">Reference</h2>\n'
            f'<p>{len(pg["index_of"])} documents that no named section claims — '
            f'specifications, dated findings, and working notes. They are here so '
            f'that links to them resolve and so search can reach them.</p>\n'
            f'<table><thead><tr><th>Document</th><th>Source</th></tr></thead>'
            f'<tbody>{rows}</tbody></table>')
    return render.TEMPLATE.format(
        title=f'{r["name"]} — Reference', repo=html.escape(r["name"].upper()),
        accent="#F5A623", src_hash="-", gen_hash=render._gen_hash(),
        tags="", nav="", body=body, published="", source_label="DOCS/",
        sitenav=nav)


def build_site(root: Path, cfg: dict, out: Path) -> tuple[int, int]:
    repos = discover(root, cfg)
    linkmap = build_linkmap(repos)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    pages_written = 0
    for r in repos:
        (out / r["slug"]).mkdir(parents=True, exist_ok=True)
        for p in r["pages"]:
            nav = build_nav(repos, r["slug"], p["slug"])
            here = f'{r["slug"]}/{p["slug"]}.html'
            dest = out / r["slug"] / f'{p["slug"]}.html'

            if p.get("index_of") is not None:
                dest.write_text(render_reference_index(r, p, nav), encoding="utf-8")
                pages_written += 1
                continue

            # Rewrite per source file: a link is relative to the document that
            # contains it, and a merged page has more than one of those.
            parts = [link_repo_nodes(
                        rewrite_links(merge_sources([q], r["path"]), q, linkmap, here),
                        repos, r["slug"], here)
                     for q in p["paths"]]
            if len(p["paths"]) == 1:
                merged = parts[0]
            else:
                chunks = []
                for q, body_md in zip(p["paths"], parts):
                    meta, body = render.parse_frontmatter(body_md)
                    chunks.append(f'## {render._doc_title(q, meta)}\n\n'
                                  f'*From `{render._source_label(q, r["path"])}`.*\n\n'
                                  f'{_demote(_strip_leading_h1(body)).strip()}\n')
                merged = "\n\n".join(chunks)

            tmp = out / r["slug"] / f'.{p["slug"]}.md'
            tmp.write_text(merged, encoding="utf-8")
            try:
                page = render.build(tmp, r["path"], sitenav=nav)
                page = page.replace(
                    f'<title>{r["name"]} — {render._doc_title(tmp, {})}</title>',
                    f'<title>{html.escape(r["name"])} — {html.escape(p["title"])}</title>')
            finally:
                tmp.unlink(missing_ok=True)
            dest.write_text(page, encoding="utf-8")
            pages_written += 1

    (out / "index.html").write_text(render_home(repos, cfg), encoding="utf-8")
    (out / "search.html").write_text(render_search_page(repos, cfg), encoding="utf-8")
    return len(repos), pages_written + 2


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", nargs="?", type=Path, default=Path.cwd())
    ap.add_argument("-c", "--config", type=Path, default=None)
    ap.add_argument("-o", "--output", type=Path, default=None)
    args = ap.parse_args()

    root = args.root.resolve()
    cfg_path = args.config or root / "site.toml"
    if not cfg_path.is_file():
        print(f"missing {cfg_path}", file=sys.stderr)
        return 2
    try:
        import tomllib
    except ModuleNotFoundError:
        # Exit 2, not 1: the check did not fail, it could not run. Everything else in cms
        # works on the floor; only reading a site.toml needs the newer stdlib.
        print("the multi-repo site builder needs Python 3.11+ for tomllib; "
              "the rest of cms runs on the declared floor", file=sys.stderr)
        return 2
    cfg = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
    out = (args.output or root / cfg.get("output", "_site")).resolve()

    try:
        n_repos, n_pages = build_site(root, cfg, out)
    except (SiteError, render.ArchFlowError, render.ArchPlotError,
            render.ArchStatError) as exc:
        print(f"{cfg_path}: {exc}", file=sys.stderr)
        return 2

    print(f"wrote {n_pages} pages across {n_repos} repos -> {out}")
    return 0


if __name__ == "__main__":
    _utf8_stdio()
    sys.exit(main())
