"""Shared helpers for the CMS skill. Pure stdlib."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterator

SKILL_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = SKILL_ROOT / "templates"

# Shipped config lives in the plugin and is versioned with it. Runtime state does
# NOT, and the distinction is load-bearing: this skill records one entry per repo
# it is run against, so its state accumulates the names of whatever ecosystem is
# using it. Written inside the plugin, that is domain content sitting in a generic
# (Tier A) plugin — the exact seam ADR-001 forbids and tests/test_seam.py enforces.
#
# It was also self-defeating. The comment here used to say state "must survive
# plugin updates, which overwrite the cached plugin dir" — and then the last
# branch wrote it into that very directory. Since neither env var is set in
# ordinary use, that branch was not a rare fallback; it was the only path ever
# taken.
SHIPPED_STATE_DIR = SKILL_ROOT / "state"          # versioned starters, no runtime writes

_state_override = os.environ.get("CMS_STATE_DIR")
if _state_override:
    STATE_DIR = Path(_state_override).expanduser()
elif os.environ.get("CLAUDE_PLUGIN_DATA"):
    STATE_DIR = Path(os.environ["CLAUDE_PLUGIN_DATA"]).expanduser() / "cms-state"
else:
    STATE_DIR = Path.home() / ".claude" / "cms-state"
STATE_DIR.mkdir(parents=True, exist_ok=True)


def _migrate_legacy_state() -> None:
    """Move state written by older versions out of the plugin directory.

    Best-effort and non-destructive: an existing file at the new location always
    wins, and any failure is silent because losing size history costs a single
    "grew >20%" warning, while crashing every cms invocation costs the skill.
    """
    if STATE_DIR == SHIPPED_STATE_DIR:
        return
    for legacy in SHIPPED_STATE_DIR.glob("*.json"):
        target = STATE_DIR / legacy.name
        try:
            if not target.exists():
                target.write_text(legacy.read_text())
            legacy.unlink()
        except OSError:
            pass


_migrate_legacy_state()

# Base allowlist: canonical doc names that must never be auto-archived. The full
# ARCHIVE_ALLOWLIST is derived below to also cover every REQUIRED_FILES entry — so a
# required doc can never be flagged as an archive candidate, and the two lists cannot
# silently drift apart.
_BASE_ALLOWLIST = {
    "README.md", "CLAUDE.md", "CHANGELOG.md",
    "VISION.md", "ARCHITECTURE.md", "ROADMAP.md",
    "LESSONS_LEARNED.md",
    # A standing constraint outlives every task by definition — archiving one because it
    # is old would delete precisely the thing that was supposed to survive the work.
    "INVARIANTS.md",
    # The `*_PLAN.md` archive pattern is aimed at transient plans — MIGRATION_PLAN,
    # PHASE2_PLAN — that stop mattering once executed. A BUSINESS_PLAN is the opposite
    # kind of document: a standing statement of what the product is, which gets *more*
    # load-bearing with age, not less. Matching it on filename alone flagged a repo's
    # primary founder document as archive-fodder purely for ending in "_PLAN".
    "BUSINESS_PLAN.md",
}

# Files that legitimately carry NO frontmatter — the root special files. This is a
# SEPARATE concern from archiving: docs under docs/ (ARCHITECTURE, ROADMAP, ...) are
# archive-allowlisted but still REQUIRE frontmatter, so they must NOT be exempted here.
# Keyed by basename; only meaningful for files under docs/ (root files are never gated).
#
# INVARIANTS.md is the one docs/ file exempted, and deliberately so: the staleness fields
# (`last_reviewed_on` / `review_in`) ask "is this still true?" on a timer, which is the
# right question for a description of the system and the wrong one for a rule about it. A
# constraint does not expire because nobody looked at it; dating one manufactures exactly
# the rot the file exists to prevent. Retirement is a deliberate edit, never a timeout.
FRONTMATTER_EXEMPT = {"README.md", "CLAUDE.md", "CHANGELOG.md", "SECURITY.md", "INVARIANTS.md"}

# Archive-candidate filename patterns (case-insensitive match on name).
ARCHIVE_PATTERNS = [
    re.compile(r".*_MIGRATION\.md$", re.IGNORECASE),
    re.compile(r".*_PLAN\.md$", re.IGNORECASE),
    re.compile(r".*_COMPLETE\.md$", re.IGNORECASE),
    re.compile(r"RUNBOOK_.*\.md$", re.IGNORECASE),
    re.compile(r".*_ASSESSMENT\.md$", re.IGNORECASE),
    re.compile(r".*_REVIEW\.md$", re.IGNORECASE),
    re.compile(r"PHASE\d*_.*\.md$", re.IGNORECASE),
]

# Required files in a per-repo skeleton.
REQUIRED_FILES = [
    "README.md",
    "CLAUDE.md",
    "CHANGELOG.md",
    "SECURITY.md",
    "docs/ARCHITECTURE.md",
    "docs/ROADMAP.md",
    "docs/LESSONS_LEARNED.md",
    "docs/THREAT_LEVEL.md",
]

REQUIRED_DIRS = [
    "docs",
    "docs/decisions",
    "docs/archive",
]

# Full allowlist: base names + the basename of every required file. Deriving it from
# REQUIRED_FILES means new required docs are auto-protected from archiving.
ARCHIVE_ALLOWLIST = _BASE_ALLOWLIST | {Path(f).name for f in REQUIRED_FILES}

# Frontmatter required fields for files under docs/.
FRONTMATTER_REQUIRED = {"title", "status", "created", "last_reviewed_on", "review_in", "applies_to"}

# `ai_summary` is OPTIONAL and deliberately stays that way — making it required would
# invalidate every document in every repo already using this schema, and a summary that
# was written to satisfy a linter is worse than none.
#
# What it is for: retrieval. Finding the right document by opening candidates costs the
# full body of everything you opened and were wrong about, so the cost of a lookup scales
# with the size of the corpus rather than with the size of the answer. A summary lets a
# reader route on titles and summaries first and open exactly one body.
#
# Which only works if the summary is bounded. An unbounded one is re-read on every triage
# pass, so it stops being an index and becomes a second copy of the document — the exact
# cost it was added to avoid. 1500 bytes is roughly a short paragraph: enough to say what
# the document is and when to open it, not enough to say what is in it.
AI_SUMMARY_MAX_BYTES = 1500

# The per-document cap bounds one row of the routing table. What a triage pass is actually
# charged is the SUM of every row, and that grows with the corpus while each summary stays
# comfortably legal — fifty documents at the cap is a table costing more than the reads it
# was built to replace, with every individual check passing. So the aggregate is bounded
# too, at roughly 5k tokens: past that, the table costs more than opening the two or three
# documents it would have saved you from opening, which is the point where the mechanism
# stops paying for itself. A Warning, never an Error — the corpus is not broken, it has
# outgrown a flat table, and the fix is usually splitting it or archiving what should not
# still be indexed rather than shaving bytes off every summary.
AI_SUMMARY_AGGREGATE_WARN_BYTES = 20000
FRONTMATTER_STATUSES = {"active", "completed", "deprecated", "Proposed", "Accepted", "Deprecated", "Superseded"}
# Controlled vocabulary for the optional `threat_level` frontmatter field (CVSS-aligned).
# Validated only when present, so docs that omit it are unaffected; used by docs/THREAT_LEVEL.md.
FRONTMATTER_THREAT_LEVELS = {"Low", "Medium", "High", "Critical"}

FENCE = "---"


@dataclass
class Finding:
    level: str  # "error" | "warning" | "info"
    file: str
    message: str

    def format(self) -> str:
        tag = {"error": "ERROR", "warning": "WARN ", "info": "INFO "}[self.level]
        return f"[{tag}] {self.file}: {self.message}"


def parse_frontmatter(text: str) -> tuple[dict[str, str], int]:
    """Return (fields, body_start_line). Empty dict if no frontmatter."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != FENCE:
        return {}, 0
    fields: dict[str, str] = {}
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == FENCE:
            return fields, i + 1
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$", line)
        if m:
            fields[m.group(1)] = m.group(2).strip()
    return {}, 0  # unterminated → treat as none


MONTH_RE = re.compile(r"^(\d+)\s*(day|week|month|year)s?$", re.IGNORECASE)

def parse_review_in(value: str) -> int | None:
    """Return number of days, or None if unparseable."""
    m = MONTH_RE.match(value.strip())
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2).lower()
    return n * {"day": 1, "week": 7, "month": 30, "year": 365}[unit]


def parse_iso_date(value: str) -> date | None:
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


ATPATH_RE = re.compile(r"@([./A-Za-z0-9_\-][A-Za-z0-9_./\-]*\.md)")

def find_atpath_imports(text: str, base: Path) -> list[tuple[str, Path]]:
    """Extract @path/to/x.md imports, resolving relative to `base` (the file's dir)."""
    results: list[tuple[str, Path]] = []
    for m in ATPATH_RE.finditer(text):
        raw = m.group(1)
        target = (base / raw).resolve()
        results.append((raw, target))
    return results


def iter_md_files(root: Path, include_archive: bool = False) -> Iterator[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune
        # "templates" holds scaffolding sources with placeholder frontmatter ({{TODAY}}),
        # not real docs — exclude so a repo bundling the cms skill doesn't lint its own templates.
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in {"node_modules", ".venv", "venv", "__pycache__", "templates"}]
        if not include_archive:
            dirnames[:] = [d for d in dirnames if d != "archive"]
        for name in filenames:
            if name.endswith(".md"):
                yield Path(dirpath) / name


def load_state(name: str) -> dict:
    path = STATE_DIR / f"{name}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_state(name: str, data: dict) -> None:
    path = STATE_DIR / f"{name}.json"
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def repo_name(repo: Path) -> str:
    return repo.resolve().name


def today_iso() -> str:
    return date.today().isoformat()
