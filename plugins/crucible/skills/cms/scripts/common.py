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

# State (size-history, sync facts) must survive plugin updates, which overwrite
# the cached plugin dir. Prefer an explicit override, then the plugin's
# persistent data dir, then a local fallback for non-plugin use.
_state_override = os.environ.get("CMS_STATE_DIR")
if _state_override:
    STATE_DIR = Path(_state_override).expanduser()
elif os.environ.get("CLAUDE_PLUGIN_DATA"):
    STATE_DIR = Path(os.environ["CLAUDE_PLUGIN_DATA"]).expanduser() / "cms-state"
else:
    STATE_DIR = SKILL_ROOT / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)

# Base allowlist: canonical doc names that must never be auto-archived. The full
# ARCHIVE_ALLOWLIST is derived below to also cover every REQUIRED_FILES entry — so a
# required doc can never be flagged as an archive candidate, and the two lists cannot
# silently drift apart.
_BASE_ALLOWLIST = {
    "README.md", "CLAUDE.md", "CHANGELOG.md",
    "VISION.md", "ARCHITECTURE.md", "ROADMAP.md",
    "LESSONS_LEARNED.md",
}

# Files that legitimately carry NO frontmatter — the root special files. This is a
# SEPARATE concern from archiving: docs under docs/ (ARCHITECTURE, ROADMAP, ...) are
# archive-allowlisted but still REQUIRE frontmatter, so they must NOT be exempted here.
# Keyed by basename; only meaningful for files under docs/ (root files are never gated).
FRONTMATTER_EXEMPT = {"README.md", "CLAUDE.md", "CHANGELOG.md", "SECURITY.md"}

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
            return json.loads(path.read_text())
        except Exception:
            return {}
    return {}


def save_state(name: str, data: dict) -> None:
    path = STATE_DIR / f"{name}.json"
    path.write_text(json.dumps(data, indent=2, sort_keys=True))


def repo_name(repo: Path) -> str:
    return repo.resolve().name


def today_iso() -> str:
    return date.today().isoformat()
