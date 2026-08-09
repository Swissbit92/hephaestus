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
import re
import shutil
import sys
import tomllib
from pathlib import Path

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
    pages = "".join(
        f'<a href="{p["slug"]}.html"'
        f'{" class=\"on\"" if p["slug"] == page_slug or (on_ref and p["slug"] == "reference") else ""}>'
        f'{html.escape(p["title"])}</a>'
        for p in listed
    )
    return (
        '<div class="snav">'
        '<div class="grp"><a class="home" href="../index.html">&#9670; ALL</a>'
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
        out.append({"slug": f"ref-{_slugify(md.stem)}", "title": md.stem.replace("_", " "),
                    "sources": [], "paths": [md], "reference": True})
    return out


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
        sitenav="",
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
            parts = [rewrite_links(merge_sources([q], r["path"]), q, linkmap, here)
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
    return len(repos), pages_written + 1


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
    sys.exit(main())
