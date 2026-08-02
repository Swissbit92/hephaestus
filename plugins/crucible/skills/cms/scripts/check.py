#!/usr/bin/env python3
"""CMS linter — tiered Error / Warning output.

Usage:
    check.py [<path>]                    # full repo audit
    check.py --mechanical <file>         # fast frontmatter + @path check (hook mode)
    check.py --file <file>               # deep single-file check

Exit codes:
    0 — no errors
    1 — one or more Error-level findings
    2 — usage error
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date, timedelta
from pathlib import Path

from common import (
    ARCHIVE_ALLOWLIST,
    ARCHIVE_PATTERNS,
    FRONTMATTER_EXEMPT,
    FRONTMATTER_REQUIRED,
    FRONTMATTER_STATUSES,
    FRONTMATTER_THREAT_LEVELS,
    REQUIRED_DIRS,
    REQUIRED_FILES,
    Finding,
    find_atpath_imports,
    iter_md_files,
    load_state,
    parse_frontmatter,
    parse_iso_date,
    parse_review_in,
    repo_name,
    save_state,
)


def check_frontmatter(path: Path, required: bool) -> list[Finding]:
    text = path.read_text(encoding="utf-8", errors="replace")
    fm, _ = parse_frontmatter(text)
    findings: list[Finding] = []
    rel = str(path)
    if not fm:
        if required:
            findings.append(Finding("error", rel, "missing frontmatter (required for files under docs/)"))
        return findings
    # Required-field completeness only applies where frontmatter is required. But any
    # frontmatter that IS present is validated for controlled-vocab + field validity even
    # on exempt files — a bad status/date on README should still be caught.
    if required:
        missing = FRONTMATTER_REQUIRED - set(fm)
        if missing:
            findings.append(Finding("error", rel, f"frontmatter missing fields: {sorted(missing)}"))
    status = fm.get("status")
    if status and status not in FRONTMATTER_STATUSES:
        findings.append(Finding("error", rel, f"invalid status '{status}'; expected one of {sorted(FRONTMATTER_STATUSES)}"))
    # threat_level controlled vocabulary (only validated when present)
    threat_level = fm.get("threat_level")
    if threat_level and threat_level not in FRONTMATTER_THREAT_LEVELS:
        findings.append(Finding("error", rel, f"invalid threat_level '{threat_level}'; expected one of {sorted(FRONTMATTER_THREAT_LEVELS)}"))
    # Date validity
    for fld in ("created", "last_reviewed_on"):
        if fld in fm and parse_iso_date(fm[fld]) is None:
            findings.append(Finding("error", rel, f"frontmatter field '{fld}' is not YYYY-MM-DD: {fm[fld]!r}"))
    if "review_in" in fm and parse_review_in(fm["review_in"]) is None:
        findings.append(Finding("error", rel, f"frontmatter 'review_in' unparseable: {fm['review_in']!r}"))
    # review_by expiry
    reviewed = parse_iso_date(fm.get("last_reviewed_on", ""))
    review_days = parse_review_in(fm.get("review_in", ""))
    if reviewed and review_days is not None:
        review_by = reviewed + timedelta(days=review_days)
        if review_by < date.today() and fm.get("status") == "active":
            findings.append(Finding("warning", rel, f"past review_by {review_by} (last_reviewed_on={reviewed}, review_in={fm['review_in']})"))
    return findings


def check_atpath_imports(path: Path) -> list[Finding]:
    text = path.read_text(encoding="utf-8", errors="replace")
    findings: list[Finding] = []
    for raw, target in find_atpath_imports(text, path.parent):
        if not target.exists():
            findings.append(Finding("error", str(path), f"@{raw} points to missing file: {target}"))
    return findings


def check_archive_candidate(path: Path) -> list[Finding]:
    name = path.name
    if name in ARCHIVE_ALLOWLIST:
        return []
    if "/archive/" in str(path).replace("\\", "/"):
        return []  # already archived
    matches_pattern = any(p.match(name) for p in ARCHIVE_PATTERNS)
    if not matches_pattern:
        return []
    # Check age
    try:
        mtime = date.fromtimestamp(path.stat().st_mtime)
    except Exception:
        return []
    age_days = (date.today() - mtime).days
    if age_days > 60:
        return [Finding("warning", str(path),
                        f"archive-candidate filename + mtime {mtime} ({age_days} days old); consider moving to docs/archive/YYYY-MM/")]
    return []


def check_required_files(repo: Path) -> list[Finding]:
    findings: list[Finding] = []
    for rel in REQUIRED_FILES:
        if not (repo / rel).exists():
            findings.append(Finding("error", str(repo / rel), f"required file missing ({rel})"))
    for rel in REQUIRED_DIRS:
        if not (repo / rel).is_dir():
            findings.append(Finding("warning", str(repo / rel), f"required dir missing ({rel}); `/cms init` would create it"))
    return findings


def check_claude_md_size_trend(repo: Path) -> list[Finding]:
    claude = repo / "CLAUDE.md"
    if not claude.exists():
        return []
    lines = len(claude.read_text(encoding="utf-8", errors="replace").splitlines())
    state = load_state("size_history")
    key = str(repo.resolve())
    entry = state.get(key, {})
    prev = entry.get("claude_md_lines")
    findings: list[Finding] = []
    findings.append(Finding("info", str(claude), f"CLAUDE.md size: {lines} lines (previous: {prev if prev is not None else 'n/a'})"))
    if prev is not None and lines > prev * 1.2 and lines > 100:
        findings.append(Finding("warning", str(claude),
                                f"CLAUDE.md grew >20% ({prev} → {lines} lines); consider extracting to docs/shared/"))
    # Persist
    entry["claude_md_lines"] = lines
    entry["last_checked"] = date.today().isoformat()
    state[key] = entry
    save_state("size_history", state)
    return findings


def check_architecture_page(repo: Path) -> list[Finding]:
    """Warn when a rendered ARCHITECTURE.html no longer matches its source.

    Warning, not error: this is advisory precisely so it stays trustworthy. A
    gate that blocks on a regenerable artifact is a gate people learn to bypass,
    and then it protects nothing. Silent when there is no rendered page — most
    repos have prose long before they have a rendered view, and flagging them
    would make the check cry wolf across the estate.
    """
    md = repo / "docs" / "ARCHITECTURE.md"
    page = repo / "docs" / "ARCHITECTURE.html"
    if not md.exists() or not page.exists():
        return []
    try:
        import render
    except Exception:                                    # noqa: BLE001
        return []
    if render.is_current(md, page):
        return []
    return [Finding("warning", str(page),
                    "generated page is out of date with ARCHITECTURE.md "
                    "— re-render with `/cms render`")]


# ── content-shape checks ────────────────────────────────────────────────────
# Nothing off the shelf does this. Vale and markdownlint reason about prose and
# formatting; neither can see that a list is shaped like a table. So these are
# hand-rolled, and the discipline that matters is false positives: developers
# tolerate roughly a 5% FP rate and stop reading warnings entirely somewhere
# past 20%. Every threshold below is set to under-report rather than over-report.
FLOW_STEP_FLOOR = 4          # a 3-hop chain is legitimate prose shorthand
TABLE_ITEM_FLOOR = 4         # 2-3 items are a list; Google and Microsoft agree
TABLE_MATCH_RATIO = 0.7
# Fences whose arrows are real syntax, not conceptual flow: shell pipes and type
# signatures. Skipping these is what keeps the arrow check honest.
CODE_LANGS = {"bash", "sh", "zsh", "shell", "console", "python", "py", "js",
              "ts", "typescript", "json", "yaml", "yml", "sql", "go", "rust"}

RE_OL_STEP = re.compile(r"^\s*\d+\.\s+\S", re.M)
RE_ARROW_STEP = re.compile(r"^\s*(->|→|├─|└─)", re.M)
# A line that is only a downward arrow, optionally with a short label after it
# ("↓ per job worker:"). Hand-drawn stage boundary — never valid in real code.
RE_CONNECTOR_LINE = re.compile(r"^[ \t]*↓[ \t]*.{0,40}$", re.M)
RE_FENCE = re.compile(r"^```([a-zA-Z0-9_-]*)\n(.*?)^```", re.S | re.M)
RE_TERM_ITEM = re.compile(r"^[-*]\s+`?\*{0,2}([A-Za-z_][\w./\[\]-]*)\*{0,2}`?\s*(—|–|:)\s+(\S.*)$")
# Anywhere in the row, not just the first cell — the ordinal is as often buried
# in a "Purpose" column ("Step 3: compile the specs") as it is in a label
# column. The literal word plus a number is unambiguous enough to search wide.
RE_ORDINAL = re.compile(r"\b(?:step|phase|stage)\s*(\d+)\b", re.I)


def _md(repo: Path) -> tuple[Path, str] | None:
    f = repo / "docs" / "ARCHITECTURE.md"
    return (f, f.read_text(encoding="utf-8")) if f.exists() else None


def check_flow_shaped_sections(repo: Path) -> list[Finding]:
    """Sequences written as prose or as an arrow cascade in a code fence.

    The omission that motivated this: `archflow` shipped, every repo already had
    its pipelines as numbered lists, and not one was converted. The first version
    of this check then missed a second wave — six arrow cascades sitting inside
    plain code fences — because it only ever looked at prose.
    """
    got = _md(repo)
    if not got:
        return []
    md, text = got
    out: list[Finding] = []

    if "```archflow" not in text:
        steps = len(RE_OL_STEP.findall(text)) + len(RE_ARROW_STEP.findall(text))
        if steps >= FLOW_STEP_FLOOR:
            out.append(Finding("warning", str(md),
                               f"{steps} sequential steps are written as prose but this doc "
                               f"has no ```archflow``` block — a sequence the reader has to "
                               f"reassemble is what archflow renders walkable"))

    # An ASCII chain is not wrong in itself — it is diffable, greppable and needs
    # no toolchain. It is wrong when it is a linear pipeline that archflow would
    # render walkable, which is what this narrower rule looks for.
    for m in RE_FENCE.finditer(text):
        lang, body = m.group(1).strip().lower(), m.group(2)
        if lang in CODE_LANGS or lang in {"archview", "archflow", "archstat", "html"}:
            continue
        # A line that is nothing but a downward arrow is a stage boundary
        # someone hand-drew. It counts as a hop: a pipeline drawn vertically is
        # still a pipeline, and counting only `->`/`→` scored the vertical ones
        # at zero — which is why the longest pipelines in the corpus, the ones
        # most worth making walkable, were the ones the rule never saw.
        drawn = len(RE_CONNECTOR_LINE.findall(body))
        hops = body.count("->") + body.count("→") + drawn
        # A conceptual pipeline is short named stages. A block dense with
        # parentheses, equals signs or commas is usually annotated code, so
        # codeyness suppresses the rule — unless the block drew its own
        # connectors, which no code listing, shell pipeline or type signature
        # ever does. Annotation density is not evidence against being a diagram.
        codey = body.count("(") + body.count("=") + body.count(",")
        if hops >= FLOW_STEP_FLOOR and (codey <= hops or drawn >= FLOW_STEP_FLOOR):
            line = text[:m.start()].count("\n") + 1
            out.append(Finding("warning", f"{md}:{line}",
                               f"a {hops}-step arrow cascade in a code fence — this is a "
                               f"pipeline drawn as text; an ```archview``` plus ```archflow``` "
                               f"makes it walkable instead of re-read"))
    return out


def check_list_shaped_like_a_table(repo: Path) -> list[Finding]:
    """Bullet lists of `term — description`, which are a table wearing a list.

    Google and Microsoft both draw the line at two-dimensional data: comparable
    attributes per row belong in a table, order-independent prose belongs in a
    list. Four items is the floor because three is genuinely a list.
    """
    got = _md(repo)
    if not got:
        return []
    md, text = got
    out, run, start = [], [], 0

    def flush(end_line: int) -> None:
        if len(run) < TABLE_ITEM_FLOOR:
            return
        hits = [x for x in run if x]
        if len(hits) / len(run) < TABLE_MATCH_RATIO:
            return
        # A value that is only code is a config example, not a description.
        if sum(1 for h in hits if h.startswith("`") and h.endswith("`")) > len(hits) / 2:
            return
        out.append(Finding("warning", f"{md}:{start}",
                           f"{len(run)} bullets shaped `term — description` — that is a "
                           f"two-column table written as a list, and a table is scannable "
                           f"where this is not"))

    lines = text.split("\n")
    in_fence = False
    for i, ln in enumerate(lines, 1):
        if ln.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if ln.startswith(("-", "*")) and ln[1:2] == " ":
            m = RE_TERM_ITEM.match(ln)
            if not run:
                start = i
            run.append(m.group(3).strip() if m else "")
        elif ln.strip() == "" and run:
            continue                       # a blank line does not end the list
        else:
            flush(i)
            run = []
    flush(len(lines))
    return out


def check_table_shaped_like_a_flow(repo: Path) -> list[Finding]:
    """Tables whose first column is a consecutive ordinal — a sequence in a grid.

    The safest of the three: ordinality is unambiguous when the labels are
    literally consecutive. Ranked-but-unlabelled tables are deliberately not
    inferred, because that is where the real false positives live.
    """
    got = _md(repo)
    if not got:
        return []
    md, text = got
    out, rows, start = [], [], 0
    in_fence = False

    def flush() -> None:
        # A contiguous run of consecutive ordinals, not a ratio over the whole
        # table. Real tables are hybrids: CRA's pipeline register holds four
        # infrastructure modules and then seven numbered steps, and a
        # whole-table ratio rule correctly refuses to call that a flow while
        # still missing the seven steps buried in it.
        best, run = [], []
        for n in rows + [None]:
            if n is not None and (not run or n == run[-1] + 1):
                run.append(n)
            else:
                if len(run) > len(best):
                    best = run
                run = [n] if n is not None else []
        if len(best) < FLOW_STEP_FLOOR:
            return
        out.append(Finding("warning", f"{md}:{start}",
                           f"{len(best)} consecutive rows numbered {best[0]}..{best[-1]} "
                           f"inside a table — that is a sequence in a grid; "
                           f"```archflow``` walks it a step at a time"))

    for i, ln in enumerate(text.split("\n"), 1):
        if ln.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if ln.strip().startswith("|"):
            if set(ln.strip()) <= set("|-: "):
                continue                    # the separator row
            if not rows:
                start = i
            m = RE_ORDINAL.search(ln)
            rows.append(int(m.group(1)) if m else None)
        elif rows:
            flush()
            rows = []
    flush()
    return out


# Some sections have a canonical form regardless of how their content is shaped.
# "Key invariants" as six long bullets slips every ratio-based rule — only half
# match `term: description` — but it is still a three-column table wearing a
# list. Matching on the section NAME is exact, so this costs no false positives.
CANONICAL_TABLE_SECTIONS = {
    "key invariants": "invariant · what it guarantees · where it is enforced",
    "invariants": "invariant · what it guarantees · where it is enforced",
    "error taxonomy": "error · class · what happens",
    "glossary": "term · what it means here",
}
# Three-plus letters, all caps, not a common English word shouted for emphasis.
RE_ACRONYM = re.compile(r"\b([A-Z]{3,6})\b")
# Emphasis in these docs is written in caps, so the extractor has to know the
# difference between an initialism and a raised voice. Everything below is a
# shouted English word, a token every reader already knows, or a ticker.
ACRONYM_STOPWORDS = {
    "THE", "AND", "NOT", "ALL", "ONE", "TWO", "NEVER", "ONLY", "MUST", "READ",
    "WRITE", "TODO", "NOTE", "AFTER", "BEFORE", "BOTH", "CANNOT", "DOES", "DONE",
    "EVERY", "FROM", "INTO", "THIS", "THAT", "WHEN", "WITH", "WHOLE", "SAME",
    "BUY", "SELL", "DATE", "TIME", "NULL", "NONE", "TRUE", "FALSE", "OFF",
    "API", "URL", "HTTP", "HTTPS", "JSON", "YAML", "HTML", "CSS", "SQL", "CPU",
    "RAM", "GPU", "SSD", "UTC", "CET", "CEST", "CSV", "REST", "CLI", "ADR",
}
GLOSSARY_ACRONYM_FLOOR = 8


def _project_words(repo: Path) -> set[str]:
    """Caps-tokens that are just this project's own name.

    A repo called `acme-exec` says ACME on every other line. That is a proper
    noun the reader is already standing inside, not a term the doc owes them a
    definition for. Derived from the path so the rule carries no project names
    of its own.
    """
    return {w.upper() for w in re.split(r"[^A-Za-z0-9]+", repo.name) if len(w) >= 3}


def check_named_section_shape(repo: Path) -> list[Finding]:
    """Sections whose name implies a table, written as bullets."""
    got = _md(repo)
    if not got:
        return []
    md, text = got
    out, lines = [], text.split("\n")
    in_fence, heading, hline, bullets, has_table = False, None, 0, 0, False

    def flush() -> None:
        if heading and bullets >= 4 and not has_table:
            out.append(Finding("warning", f"{md}:{hline}",
                               f'"{heading}" is {bullets} bullets — a section with '
                               f'this name reads as a table: {CANONICAL_TABLE_SECTIONS[heading.lower()]}'))

    for i, ln in enumerate(lines, 1):
        if ln.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if ln.startswith("## "):
            flush()
            title = ln[3:].strip()
            heading = title if title.lower() in CANONICAL_TABLE_SECTIONS else None
            hline, bullets, has_table = i, 0, False
        elif heading:
            if ln.startswith(("-", "*")) and ln[1:2] == " ":
                bullets += 1
            elif ln.strip().startswith("|"):
                has_table = True
    flush()
    return out


def check_missing_glossary(repo: Path) -> list[Finding]:
    """A doc thick with acronyms and no glossary.

    Not "every doc needs one" — most do not. The signal is density: past a
    handful of distinct initialisms the reader is being asked to already know
    the vocabulary, which is exactly the assumption a glossary exists to drop.
    """
    got = _md(repo)
    if not got:
        return []
    md, text = got
    if re.search(r"^##\s+glossary", text, re.I | re.M):
        return []
    ignore = ACRONYM_STOPWORDS | _project_words(repo)
    found = {a for a in RE_ACRONYM.findall(text) if a not in ignore}
    if len(found) < GLOSSARY_ACRONYM_FLOOR:
        return []
    sample = ", ".join(sorted(found)[:6])
    return [Finding("warning", str(md),
                    f"{len(found)} distinct acronyms ({sample}…) and no Glossary "
                    f"section — the doc assumes a vocabulary it never defines")]
_NO_CHECK = {"", "none", "none yet", "todo", "tbd", "-", "n/a"}


def check_invariants_have_checks(repo: Path) -> list[Finding]:
    """Warn about a standing constraint that is stated but not enforceable.

    Warning, never error — and that distinction is the design, not a compromise. An
    invariant with no check is still worth having written down; erroring on one would
    teach people to stop writing them down, which costs more than the missing check. The
    nudge points at the gap without punishing the intent.

    No file means nothing to say: a repo with no standing constraints is not a repo doing
    something wrong.
    """
    path = repo / "docs" / "INVARIANTS.md"
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    findings: list[Finding] = []
    state = {"title": None, "status": "active", "check": ""}

    def flush() -> None:
        title = state["title"]
        if (title and "{{" not in title                       # skip the scaffold placeholder
                and state["status"].strip().lower() == "active"
                and state["check"].strip().lower() in _NO_CHECK):
            findings.append(Finding(
                "warning", str(path),
                f"invariant '{title}' is active but has no Check: — stated, not enforced. "
                "Rewrite it in a falsifiable form and wire a check to it."))

    for line in text.splitlines():
        s = line.strip()
        if s.startswith("## "):
            flush()
            state.update(title=s[3:].strip(), status="active", check="")
        elif state["title"]:
            low = s.lower()
            if low.startswith("status:"):
                state["status"] = s.split(":", 1)[1]
            elif low.startswith("check:"):
                state["check"] = s.split(":", 1)[1]
    flush()
    return findings


def run_repo_check(repo: Path) -> list[Finding]:
    findings: list[Finding] = []
    findings.extend(check_required_files(repo))
    findings.extend(check_claude_md_size_trend(repo))
    findings.extend(check_architecture_page(repo))
    findings.extend(check_flow_shaped_sections(repo))
    findings.extend(check_list_shaped_like_a_table(repo))
    findings.extend(check_table_shaped_like_a_flow(repo))
    findings.extend(check_named_section_shape(repo))
    findings.extend(check_missing_glossary(repo))
    findings.extend(check_invariants_have_checks(repo))
    # Per-file checks
    for md in iter_md_files(repo, include_archive=False):
        required_fm = "/docs/" in str(md).replace("\\", "/") and md.name not in FRONTMATTER_EXEMPT
        findings.extend(check_frontmatter(md, required=required_fm))
        findings.extend(check_atpath_imports(md))
        findings.extend(check_archive_candidate(md))
    return findings


def run_mechanical_check(file: Path) -> list[Finding]:
    """Fast, hook-safe: frontmatter presence (if under docs/) + @path validity only."""
    findings: list[Finding] = []
    if not file.exists():
        return []  # new file; other rules caught at save time
    required_fm = "/docs/" in str(file).replace("\\", "/") and file.name not in FRONTMATTER_EXEMPT
    findings.extend(check_frontmatter(file, required=required_fm))
    findings.extend(check_atpath_imports(file))
    return findings


def main() -> int:
    ap = argparse.ArgumentParser(description="CMS linter")
    ap.add_argument("path", nargs="?", default=".", help="repo path (default: .)")
    ap.add_argument("--mechanical", metavar="FILE", help="fast check on one file (hook mode)")
    ap.add_argument("--file", metavar="FILE", help="deep check on one file")
    args = ap.parse_args()

    if args.mechanical:
        findings = run_mechanical_check(Path(args.mechanical))
    elif args.file:
        f = Path(args.file)
        required_fm = "/docs/" in str(f).replace("\\", "/") and f.name not in FRONTMATTER_EXEMPT
        findings = check_frontmatter(f, required=required_fm) + check_atpath_imports(f) + check_archive_candidate(f)
    else:
        repo = Path(args.path).resolve()
        if not repo.is_dir():
            print(f"error: not a directory: {repo}", file=sys.stderr)
            return 2
        print(f"CMS check: {repo_name(repo)} ({repo})")
        findings = run_repo_check(repo)

    errors = [f for f in findings if f.level == "error"]
    warnings = [f for f in findings if f.level == "warning"]
    infos = [f for f in findings if f.level == "info"]

    for f in errors + warnings + infos:
        print(f.format())

    print()
    print(f"Summary: {len(errors)} error(s), {len(warnings)} warning(s), {len(infos)} info(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
