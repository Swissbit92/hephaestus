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

# Standard artifact fragments a .gitignore is expected to cover. We report which are
# absent so the DevOps lens knows what hygiene the repo hasn't declared.
GITIGNORE_EXPECTED: tuple[str, ...] = (
    "__pycache__", ".pytest_cache", "node_modules", ".coverage", "htmlcov",
    "dist", "build", ".env", "*.log",
)

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
            capture_output=True, text=True, check=True,
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


def _gitignore_gaps(root: Path) -> tuple[bool, list[str]]:
    gi = root / ".gitignore"
    if not gi.exists():
        return False, list(GITIGNORE_EXPECTED)
    try:
        body = gi.read_text(errors="replace")
    except OSError:
        return True, list(GITIGNORE_EXPECTED)
    present_lines = {ln.strip().rstrip("/") for ln in body.splitlines()
                     if ln.strip() and not ln.strip().startswith("#")}
    gaps = []
    for expected in GITIGNORE_EXPECTED:
        needle = expected.rstrip("/*").lstrip("*").lstrip(".")
        if not any(needle in ln for ln in present_lines):
            gaps.append(expected)
    return True, gaps


def _python_dead_module_candidates(records: list[tuple[str, Path]]) -> list[str]:
    """Conservative, low-confidence: a .py module whose basename is never referenced in an
    import statement anywhere in the tree. Excludes entrypoints, __init__, tests, and
    anything with a `__main__` guard (runnable scripts). False positives are possible
    (dynamic imports, plugin discovery) — this is a *candidate* list the Janitor lens
    verifies, never an assertion of death.
    """
    py = [(rel, ap) for rel, ap in records if rel.endswith(".py")]
    # Build the corpus of import references once.
    import_re = re.compile(r"^\s*(?:from|import)\s+([\w.]+)", re.MULTILINE)
    referenced: set[str] = set()
    bodies: dict[str, str] = {}
    for rel, ap in py:
        try:
            text = ap.read_text(errors="replace")
        except OSError:
            text = ""
        bodies[rel] = text
        for m in import_re.finditer(text):
            # record every dotted segment: `from a.b.c import x` -> a, b, c
            for seg in m.group(1).split("."):
                if seg:
                    referenced.add(seg)
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
                    text = ap.read_text(errors="replace")
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

    gi_present, gi_gaps = _gitignore_gaps(root)
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


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    patterns = tuple(args.flag_patterns) if args.flag_patterns else DEFAULT_FLAG_PATTERNS
    m = collect(args.root, god_threshold=args.god_threshold, flag_patterns=patterns)
    print(m.to_json())
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
