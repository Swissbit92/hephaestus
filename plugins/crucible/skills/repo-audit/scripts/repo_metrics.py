#!/usr/bin/env python3
"""Deterministic repo-health metrics — the reproducible anchor of a repo-audit.

Pure stdlib, no domain references, drops into any repo. The point of this module is
*reproducibility*: an LLM asked "how healthy is this repo?" wobbles run-to-run, so the
qualitative lenses of an audit can't be trended on their own. This script computes hard,
byte-and-line-exact facts and a deterministic `anchor_score` from them — the same repo at
the same commit always yields the same number, so an audit can honestly say "score went
72 -> 68 since last quarter" and mean it.

The LLM lenses (dead-code / structure / clean-code / config-hygiene) read these metrics as
ground truth and layer judgment on top. They never recompute the numbers.

Design constraints:
- Pure stdlib. No pip installs, ever (Tier-A vendor-neutral rule).
- Deterministic: no timestamps, no randomness, sorted outputs, stable tie-breaks.
- Language-light: works on any tree by extension; the few language-specific heuristics
  (Python dead-module candidates) are clearly labelled low-confidence and never dominate
  the score.
- Injectable file list: `collect(root, files=...)` takes an explicit file list so tests
  are hermetic; when omitted it shells out to `git ls-files` (tracked files only — the
  audit judges what's *committed*, not local scratch).

CLI:  python3 repo_metrics.py [ROOT] [--json] [--god-threshold N] [--flag-pattern RE ...]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------- constants

# Source extensions we count lines of code for (God-file detection operates on these).
SOURCE_EXTS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".go", ".rs", ".java",
    ".kt", ".rb", ".php", ".c", ".h", ".cc", ".cpp", ".hpp", ".cs", ".swift",
    ".scala", ".sh", ".bash", ".sql", ".vue", ".svelte",
}

# A file over this many lines is a "God file" candidate — one file doing too much.
DEFAULT_GOD_THRESHOLD = 500

# A tracked binary/asset over this many bytes is worth a human glance (accidental commit
# of a build artifact, a checked-in DB, a giant fixture). Not inherently wrong — flagged.
LARGE_FILE_BYTES = 1_000_000

# Glob-ish fragments that should almost never be *tracked* in git. Presence of a tracked
# path matching any of these is a hygiene violation (build/test artifacts, caches, secrets,
# local DBs). Matched against the posix path, case-sensitively where it matters.
ARTIFACT_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"(^|/)__pycache__(/|$)", "python bytecode cache"),
    (r"(^|/)\.pytest_cache(/|$)", "pytest cache"),
    (r"(^|/)\.ruff_cache(/|$)", "ruff cache"),
    (r"(^|/)\.mypy_cache(/|$)", "mypy cache"),
    (r"(^|/)node_modules(/|$)", "node_modules"),
    (r"(^|/)htmlcov(/|$)", "coverage html report"),
    (r"(^|/)\.coverage$", "coverage data file"),
    (r"(^|/)dist(/|$)", "build output (dist)"),
    (r"(^|/)build(/|$)", "build output"),
    (r"\.egg-info(/|$)", "python egg metadata"),
    (r"\.(db|sqlite|sqlite3)$", "committed database file"),
    (r"\.log$", "log file"),
    (r"\.(pyc|pyo)$", "compiled python"),
    (r"(^|/)\.DS_Store$", "macOS finder metadata"),
    (r"(^|/)\.env(\.[^/]+)?$", "environment / secrets file"),
)
# `.env.example` / `.env.template` / `.env.sample` are the *documented* key list, not a
# secret — they're meant to be tracked. Exempt them from the .env artifact rule.
ENV_EXEMPT = re.compile(r"(^|/)\.env\.(example|template|sample|dist)$")

# Artifact fragments a .gitignore is expected to cover, each paired with the evidence that
# the repo could actually produce that artifact.
#
# A flat list charged every repo for every ecosystem: a pure-stdlib Python repo with no
# build step was docked for not ignoring `node_modules`, `dist` and `build`, which it can
# never generate. That is not a small inaccuracy — it is most of a penalty, and a score
# that is wrong for reasons the reader can see is a score the reader stops using. The
# gate is per-entry evidence, not a project-type guess, because a repo can be several
# things at once and usually is.
#
# Keys are the fragment; values are the marker files that make it relevant. An empty
# tuple means "always relevant" — a secret or a stray log can appear in any repo.
GITIGNORE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("__pycache__", ("*.py",)),
    (".pytest_cache", ("pytest.ini", "setup.cfg", "pyproject.toml", "tox.ini", "conftest.py")),
    ("node_modules", ("package.json",)),
    (".coverage", (".coveragerc", "pyproject.toml", "setup.cfg", "tox.ini")),
    ("htmlcov", (".coveragerc", "pyproject.toml", "setup.cfg", "tox.ini")),
    ("dist", ("setup.py", "pyproject.toml", "package.json", "Cargo.toml")),
    ("build", ("setup.py", "pyproject.toml", "package.json", "Makefile", "CMakeLists.txt")),
    (".env", ()),
    ("*.log", ()),
)

# Kept for consumers that imported the old name. Derived, so the two cannot drift apart.
GITIGNORE_EXPECTED: tuple[str, ...] = tuple(frag for frag, _ in GITIGNORE_RULES)

# Default heuristics for "feature flag" reads, generic across the common stacks. Purely a
# count of how much conditional-on-config branching exists — high counts feed the
# clean-code lens's "combinatorial flag branching?" question and the flag-gate concern.
DEFAULT_FLAG_PATTERNS: tuple[str, ...] = (
    r"os\.getenv\(",          # python: os.getenv(...)
    r"os\.environ",           # python: os.environ[...] / .get(...)
    r"process\.env\.",        # node: process.env.FOO
    r"(?<![.\w])getenv\(",    # bare getenv( (C / PHP / `from os import getenv`);
    #                           lookbehind avoids double-counting os.getenv above
)


# --------------------------------------------------------------------------- data model

@dataclass
class ExtStat:
    ext: str
    files: int
    bytes: int
    lines: int


@dataclass
class FileLines:
    path: str
    lines: int


@dataclass
class FileBytes:
    path: str
    bytes: int


@dataclass
class ArtifactHit:
    path: str
    reason: str


@dataclass
class FlagHit:
    path: str
    hits: int


@dataclass
class ScoreBreakdown:
    """How the anchor_score was derived — fully auditable, every penalty itemised."""
    start: int
    god_file_penalty: int
    artifact_penalty: int
    gitignore_gap_penalty: int
    large_file_penalty: int
    dead_candidate_penalty: int
    final: int


@dataclass
class Metrics:
    root: str
    file_count: int
    total_bytes: int
    total_source_lines: int
    by_ext: list[ExtStat]
    god_files: list[FileLines]
    god_threshold: int
    largest_files: list[FileBytes]
    tracked_artifacts: list[ArtifactHit]
    gitignore_present: bool
    gitignore_gaps: list[str]
    flag_hits: list[FlagHit]
    flag_hit_total: int
    dead_module_candidates: list[str]
    anchor_score: int
    score_breakdown: ScoreBreakdown
    notes: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=False)


# --------------------------------------------------------------------------- file listing

def _git_tracked_files(root: Path) -> list[str] | None:
    """Return git-tracked paths (posix, repo-relative), or None if not a git repo."""
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return [p for p in out.stdout.split("\0") if p]


def _walk_files(root: Path) -> list[str]:
    """Fallback when not a git repo: walk the tree, skipping obvious vendor/cache dirs."""
    skip_dirs = {
        ".git", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache",
        "node_modules", "htmlcov", ".venv", "venv", "dist", "build",
    }
    files: list[str] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if any(part in skip_dirs for part in rel.parts):
            continue
        files.append(rel.as_posix())
    return files


def _count_lines(path: Path) -> int:
    """Line count, binary-safe. Non-text or unreadable files count as 0 lines."""
    try:
        data = path.read_bytes()
    except OSError:
        return 0
    if b"\0" in data[:4096]:  # crude binary sniff
        return 0
    if not data:
        return 0
    return data.count(b"\n") + (0 if data.endswith(b"\n") else 1)


# --------------------------------------------------------------------------- pure analysers
# Each takes the resolved (path, abspath, size, lines) records and returns a slice of the
# report. Kept pure and separately testable.

def _is_artifact(posix_path: str) -> str | None:
    if ENV_EXEMPT.search(posix_path):
        return None
    for pat, reason in ARTIFACT_PATTERNS:
        if re.search(pat, posix_path):
            return reason
    return None


def _relevant_gitignore_fragments(root: Path, files: list) -> list:
    """The fragments this repo could actually produce, given what is in it.

    Charging a repo for not ignoring artifacts it cannot generate is the difference
    between a metric that is merely noisy and one that is wrong, and a reader who can see
    it is wrong stops reading the rest of the number too.
    """
    names = {Path(f).name for f in files}
    suffixes = {Path(f).suffix for f in files}

    def present(marker: str) -> bool:
        if marker.startswith("*."):
            return marker[1:] in suffixes
        return marker in names

    return [frag for frag, markers in GITIGNORE_RULES
            if not markers or any(present(m) for m in markers)]


def _gitignore_gaps(root: Path, files: list = None) -> tuple[bool, list[str]]:
    relevant = (_relevant_gitignore_fragments(root, files) if files is not None
                else list(GITIGNORE_EXPECTED))
    gi = root / ".gitignore"
    if not gi.exists():
        return False, relevant
    try:
        body = gi.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return True, relevant
    present_lines = {ln.strip().rstrip("/") for ln in body.splitlines()
                     if ln.strip() and not ln.strip().startswith("#")}
    gaps = [expected for expected in relevant
            if not _covered_by(expected, present_lines)]
    return True, gaps


def _covered_by(fragment: str, entries: set) -> bool:
    """Is `fragment` actually ignored by one of these .gitignore entries?

    Matched against whole normalised entries, never as a substring. The substring version
    silently reported `.env` as covered in any repo containing a `.venv/` line, because
    stripping the leading dot leaves the needle `env`, which `.venv` contains. That is the
    worst possible false negative for this check to have: it hides the one entry whose
    absence can publish a credential, and it hid it in every Python repo using a virtualenv
    — including this one, where it went unnoticed until a full audit went looking.

    A negation (`!.env.example`) is not coverage; it is an explicit re-inclusion, so it is
    skipped rather than counted as a match.
    """
    target = fragment.strip().lstrip("*").rstrip("/")
    for raw in entries:
        entry = raw.strip()
        if not entry or entry.startswith("!"):
            continue
        entry = entry.lstrip("/").rstrip("/")
        if entry == fragment or entry == target:
            return True
        # `.env` is covered by `.env*` / `.env.*`; `dist` by `dist/` (already stripped).
        if entry.endswith("*") and target.startswith(entry.rstrip("*").rstrip(".")):
            return True
        # `*.log` is covered by an entry that ends the same way.
        if fragment.startswith("*.") and entry.endswith(fragment[1:]):
            return True
    return False


def _python_dead_module_candidates(records: list[tuple[str, Path]]) -> list[str]:
    """Conservative, low-confidence: a .py module whose basename is never referenced in an
    import statement anywhere in the tree. Excludes entrypoints, __init__, tests, and
    anything with a `__main__` guard (runnable scripts). False positives are possible
    (dynamic imports, plugin discovery) — this is a *candidate* list the Janitor lens
    verifies, never an assertion of death.
    """
    py = [(rel, ap) for rel, ap in records if rel.endswith(".py")]
    # Build the corpus of import references once.
    #
    # BOTH halves of a `from X import a, b` are recorded, and that is the whole point.
    # Matching only the module path after `from` missed every submodule imported the most
    # ordinary way there is — `from harness import runner, scoring`, `from . import db, nl`
    # — so a package's own modules were reported as dead while being imported on the very
    # next line. On this repo that was a 100% false-positive rate: all six candidates were
    # live. A dead-code metric that is wrong about live code does not get used carefully,
    # it gets ignored.
    # Same-line whitespace only. `\s` inside a character class matches newlines too, so
    # `[\w.,\s]+` swallows the following lines and the capture stops being one import
    # statement — which silently broke EVERY bare `import x`, not just unusual ones.
    from_re = re.compile(r"^[^\S\n]*from[^\S\n]+([\w.]*)[^\S\n]+import[^\S\n]+(.+)$",
                         re.MULTILINE)
    import_re = re.compile(r"^[^\S\n]*import[^\S\n]+(.+)$", re.MULTILINE)
    referenced: set[str] = set()
    bodies: dict[str, str] = {}

    def _record_dotted(raw: str) -> None:
        for seg in raw.split("."):
            seg = seg.strip()
            if seg:
                referenced.add(seg)

    for rel, ap in py:
        try:
            text = ap.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        bodies[rel] = text
        for m in from_re.finditer(text):
            _record_dotted(m.group(1))          # the package path
            names = m.group(2).split("#")[0]    # drop a trailing comment
            names = names.replace("(", " ").replace(")", " ").replace("*", " ")
            for part in names.split(","):
                # `from x import y as z` — `y` is the module that is actually referenced.
                name = part.strip().split(" as ")[0].strip()
                if name:
                    _record_dotted(name)
        for m in import_re.finditer(text):
            # `import x  # noqa: E402` is ordinary in this repo (sys.path juggling before
            # imports), so the trailing comment has to come off before splitting.
            for part in m.group(1).split("#")[0].split(","):
                _record_dotted(part.strip().split(" as ")[0])
    candidates: list[str] = []
    for rel, _ap in py:
        stem = Path(rel).stem
        if stem in {"__init__", "__main__", "conftest", "setup"}:
            continue
        if stem.startswith("test_") or "/tests/" in f"/{rel}" or rel.startswith("tests/"):
            continue
        if "__main__" in bodies.get(rel, ""):  # runnable script/CLI entrypoint
            continue
        if stem not in referenced:
            candidates.append(rel)
    return sorted(candidates)


# --------------------------------------------------------------------------- scoring

def _score(*, god_files: list[FileLines], god_threshold: int,
           artifacts: list[ArtifactHit], gitignore_gaps: list[str],
           large_files: list[FileBytes], dead_candidates: list[str]) -> ScoreBreakdown:
    """Deterministic anchor score in [0, 100]. Every penalty is bounded and itemised so
    the number is explainable and reproducible — this is the value you trend over time.

    Weighting rationale (honest, coarse — this is a health *indicator*, not a gauge):
    - God files: the dominant structural-debt signal. 4 pts each, scaled up to 3x for a
      file that is >=3x the threshold. Capped so one monster file can't zero the score.
    - Tracked artifacts: pure hygiene, cheap to fix, so 3 pts each, capped.
    - .gitignore gaps: 2 pts per missing standard pattern, capped.
    - Oversized tracked files: 2 pts each, capped (assets are often legitimate).
    - Dead-module candidates: low-confidence, so weak — 1 pt each, capped low.
    """
    start = 100

    god_pen = 0
    for g in god_files:
        over = g.lines / god_threshold if god_threshold else 1.0
        god_pen += 4 * min(3.0, max(1.0, over))
    god_pen = min(40, round(god_pen))

    art_pen = min(24, 3 * len(artifacts))
    gap_pen = min(12, 2 * len(gitignore_gaps))
    large_pen = min(10, 2 * len(large_files))
    dead_pen = min(6, len(dead_candidates))

    final = start - god_pen - art_pen - gap_pen - large_pen - dead_pen
    final = max(0, min(100, final))
    return ScoreBreakdown(
        start=start, god_file_penalty=god_pen, artifact_penalty=art_pen,
        gitignore_gap_penalty=gap_pen, large_file_penalty=large_pen,
        dead_candidate_penalty=dead_pen, final=final,
    )


# --------------------------------------------------------------------------- orchestration

def collect(root: str | Path, *, files: list[str] | None = None,
            god_threshold: int = DEFAULT_GOD_THRESHOLD,
            flag_patterns: tuple[str, ...] = DEFAULT_FLAG_PATTERNS,
            largest_n: int = 15) -> Metrics:
    """Compute the full metrics report for `root`.

    `files` — explicit repo-relative posix paths to analyse. When None, uses git-tracked
    files, falling back to a filtered walk for non-git trees. Passing `files` keeps callers
    (and tests) hermetic and deterministic.
    """
    root = Path(root).resolve()
    notes: list[str] = []
    if files is None:
        tracked = _git_tracked_files(root)
        if tracked is None:
            files = _walk_files(root)
            notes.append("not a git repo — analysed a filtered filesystem walk, not tracked files")
        else:
            files = tracked
    files = sorted(set(files))

    # Resolve records once: (relpath, abspath, size, lines).
    records: list[tuple[str, Path, int, int]] = []
    flag_res = [re.compile(p) for p in flag_patterns]
    ext_acc: dict[str, ExtStat] = {}
    god: list[FileLines] = []
    largest: list[FileBytes] = []
    artifacts: list[ArtifactHit] = []
    flags: list[FlagHit] = []
    total_bytes = 0
    total_source_lines = 0

    for rel in files:
        ap = root / rel
        try:
            size = ap.stat().st_size if ap.exists() else 0
        except OSError:
            size = 0
        ext = Path(rel).suffix.lower()
        is_source = ext in SOURCE_EXTS
        lines = _count_lines(ap) if is_source else 0
        records.append((rel, ap, size, lines))
        total_bytes += size

        reason = _is_artifact(rel)
        if reason:
            artifacts.append(ArtifactHit(path=rel, reason=reason))

        if size >= LARGE_FILE_BYTES:
            largest.append(FileBytes(path=rel, bytes=size))

        if is_source:
            total_source_lines += lines
            st = ext_acc.setdefault(ext, ExtStat(ext=ext, files=0, bytes=0, lines=0))
            st.files += 1
            st.bytes += size
            st.lines += lines
            if lines >= god_threshold:
                god.append(FileLines(path=rel, lines=lines))
            # flag grep (text source files only)
            if flag_res:
                try:
                    text = ap.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    text = ""
                n = sum(len(r.findall(text)) for r in flag_res)
                if n:
                    flags.append(FlagHit(path=rel, hits=n))
        else:
            st = ext_acc.setdefault(ext or "<none>", ExtStat(ext=ext or "<none>", files=0, bytes=0, lines=0))
            st.files += 1
            st.bytes += size

    by_ext = sorted(ext_acc.values(), key=lambda s: (-s.bytes, s.ext))
    god.sort(key=lambda f: (-f.lines, f.path))
    largest.sort(key=lambda f: (-f.bytes, f.path))
    largest = largest[:largest_n]
    artifacts.sort(key=lambda a: a.path)
    flags.sort(key=lambda f: (-f.hits, f.path))
    flag_total = sum(f.hits for f in flags)

    gi_present, gi_gaps = _gitignore_gaps(root, files)
    dead = _python_dead_module_candidates([(rel, ap) for rel, ap, _s, _l in records])

    breakdown = _score(
        god_files=god, god_threshold=god_threshold, artifacts=artifacts,
        gitignore_gaps=gi_gaps, large_files=largest, dead_candidates=dead,
    )

    return Metrics(
        root=str(root),
        file_count=len(files),
        total_bytes=total_bytes,
        total_source_lines=total_source_lines,
        by_ext=by_ext,
        god_files=god,
        god_threshold=god_threshold,
        largest_files=largest,
        tracked_artifacts=artifacts,
        gitignore_present=gi_present,
        gitignore_gaps=gi_gaps,
        flag_hits=flags,
        flag_hit_total=flag_total,
        dead_module_candidates=dead,
        anchor_score=breakdown.final,
        score_breakdown=breakdown,
        notes=notes,
    )


# --------------------------------------------------------------------------- CLI

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Deterministic repo-health metrics (the reproducible anchor of a repo-audit).",
    )
    p.add_argument("root", nargs="?", default=".", help="repo root (default: cwd); emits a full JSON report")
    p.add_argument("--god-threshold", type=int, default=DEFAULT_GOD_THRESHOLD,
                   help=f"lines over which a source file is a God-file candidate (default {DEFAULT_GOD_THRESHOLD})")
    p.add_argument("--flag-pattern", action="append", dest="flag_patterns", default=None,
                   help="regex for a config/flag read; repeatable (default: common env-read idioms)")
    return p


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


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    patterns = tuple(args.flag_patterns) if args.flag_patterns else DEFAULT_FLAG_PATTERNS
    m = collect(args.root, god_threshold=args.god_threshold, flag_patterns=patterns)
    print(m.to_json())
    return 0


if __name__ == "__main__":  # pragma: no cover
    _utf8_stdio()
    sys.exit(main())
