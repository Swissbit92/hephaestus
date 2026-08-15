#!/usr/bin/env python3
"""Lint the marketplace's skills for the defects that manifests cannot see.

`validate_manifests.py` proves a plugin is well-formed. `test_seam.py` proves it is
domain-free. Neither can see the two ways a *skill library* actually decays:

- **A skill outgrows its budget.** A SKILL.md is read into context before the model can
  judge whether it was needed, so length is a tax paid on every session that loads it.
  Nothing was watching this, and it only ever drifts upward.
- **Two skills start saying the same thing.** Descriptions are what the model routes on,
  so overlapping ones make the choice between two skills arbitrary — and duplicated
  prose in the bodies means a rule fixed in one place stays wrong in the other. This is
  invisible in review, because no single diff introduces it.

Detection is textual and deterministic — no model, no network. Descriptions are compared
by Jaccard similarity over content words; bodies by counting shared 12-word shingles,
with fenced code stripped first (two skills legitimately quoting the same command is not
duplicated prose). Token cost is estimated as UTF-8 bytes / 4, which is an approximation
and deliberately reported as one.

Exit codes:
    0 — no findings above the failing severity
    1 — at least one ERROR (or, with --strict, at least one WARN)
    2 — could not determine: no skills found, or a SKILL.md could not be read. NOT a pass.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# A SKILL.md is loaded before its usefulness is known, so its size is a standing cost.
# 3000 is not a law of nature; it is the point past which every skill here that crossed
# it was carrying reference material that belonged in a sibling file.
TOKEN_WARN = 3000

# Jaccard over content words. Two descriptions above this are close enough that a model
# routing between them is guessing.
OVERLAP_WARN = 0.35

# Words per shingle. Long enough that a shared sentence fragment is deliberate rather
# than coincidental; short enough to catch a paraphrase that kept the clause order.
SHINGLE = 12

# Overlap is measured in DISTINCT shared passages, never in shared windows.
#
# This distinction is the whole check. Sliding 12-word windows over one shared sentence
# yields nine or ten "shared shingles", so a naive count reports a single deliberate
# cross-reference as nine duplications — and the first two the linter found in this repo
# were exactly that: each skill naming its sibling to tell the reader which one to reach
# for. Merging overlapping windows back into maximal runs makes the number mean what the
# reader assumes it means.
DUP_RUNS_WARN = 2

# A single shared run is only worth reporting once it is longer than a sentence. A skill
# that says "spar-with-me helps you decide what to do; grill-me talks you out of it" is
# doing its job; a shared block this long is a paragraph someone pasted.
DUP_LONGEST_WARN = 30

# Frontmatter keys this marketplace sanctions. `name` and `description` are required by
# every agent runtime; the rest are known-inert or known-honoured. Anything else is a
# portability risk, because its behaviour in a runtime that does not know it is untested.
SANCTIONED_KEYS = {"name", "description", "disable-model-invocation", "metadata"}

STOP = frozenset("""
a an the and or of to for in on with without use used using when this that it its is are
be by as at from into out up down not no if then than so such via per about over under
you your they their we our i me my he she them his her at can may must should will would
""".split())

WORD_RE = re.compile(r"[a-z0-9][a-z0-9'-]*")
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
FENCE_RE = re.compile(r"^```.*?^```", re.M | re.S)

ERROR, WARN = "ERROR", "WARN"


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


class Finding:
    """One lint result. Ordered ERROR-first for reporting."""

    def __init__(self, level: str, subject: str, code: str, message: str) -> None:
        self.level = level
        self.subject = subject
        self.code = code
        self.message = message

    def as_dict(self) -> dict[str, str]:
        return {"level": self.level, "subject": self.subject,
                "code": self.code, "message": self.message}

    def __str__(self) -> str:
        return f"  {self.level:<5} {self.subject}  [{self.code}]  {self.message}"


def words(text: str) -> list[str]:
    return WORD_RE.findall(text.lower())


def content_words(text: str) -> set[str]:
    """Words that carry routing meaning: stopwords and 1-2 char tokens removed."""
    return {w for w in words(text) if w not in STOP and len(w) > 2}


def jaccard(a: str, b: str) -> float:
    sa, sb = content_words(a), content_words(b)
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    return inter / (len(sa) + len(sb) - inter)


def prose_words(body: str) -> list[str]:
    """Body words with fenced code removed.

    Code is stripped because two skills quoting the same `git` invocation is correct
    reuse, not duplicated instruction — counting it would bury the prose signal in
    false positives.
    """
    return words(FENCE_RE.sub(" ", body))


def shingles(body: str) -> set[str]:
    """The set of 12-word windows over a body's prose."""
    w = prose_words(body)
    return {" ".join(w[i:i + SHINGLE]) for i in range(len(w) - SHINGLE + 1)}


def shared_passages(a_body: str, b_body: str) -> list[str]:
    """Maximal shared word-runs between two bodies, longest first.

    Walks A's windows in order and merges consecutive shared ones back into a single
    run, so one duplicated sentence is reported as one passage rather than as the ten
    overlapping windows that cover it.
    """
    wa = prose_words(a_body)
    wb_shingles = shingles(b_body)
    if len(wa) < SHINGLE or not wb_shingles:
        return []

    runs: list[str] = []
    start: int | None = None
    for i in range(len(wa) - SHINGLE + 1):
        if " ".join(wa[i:i + SHINGLE]) in wb_shingles:
            if start is None:
                start = i
        elif start is not None:
            runs.append(" ".join(wa[start:i + SHINGLE - 1]))
            start = None
    if start is not None:
        runs.append(" ".join(wa[start:]))
    return sorted(runs, key=lambda r: -len(r.split()))


def parse_frontmatter(text: str) -> tuple[dict[str, str], str, str | None]:
    """(frontmatter, body, error). Deliberately minimal: this validates the shape the
    runtimes actually read, and a full YAML parser would accept documents they do not."""
    if not text.startswith("---"):
        return {}, text, "no YAML frontmatter (file must open with ---)"
    end = re.search(r"^---\s*$", text[3:], re.M)
    if not end:
        return {}, text, "frontmatter is not terminated by a closing ---"
    raw, body = text[3:3 + end.start()], text[3 + end.end():]
    fm: dict[str, str] = {}
    for line in raw.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        if line[:1] in (" ", "\t"):
            continue  # a nested value under the previous key (e.g. metadata:)
        key, sep, value = line.partition(":")
        if not sep:
            continue
        fm[key.strip()] = value.strip().strip('"').strip("'")
    return fm, body, None


def find_skills(root: Path) -> list[Path]:
    return sorted(root.glob("plugins/*/skills/*/SKILL.md"))


def lint_one(path: Path, root: Path) -> tuple[dict, list[Finding]]:
    """Per-skill checks. Returns the parsed skill and its findings."""
    rel = path.relative_to(root).as_posix()
    text = path.read_text(encoding="utf-8", errors="replace")
    fm, body, err = parse_frontmatter(text)
    name = fm.get("name", "")
    subject = name or path.parent.name
    findings: list[Finding] = []

    if err:
        findings.append(Finding(ERROR, subject, "frontmatter", f"{err} ({rel})"))

    for key in ("name", "description"):
        if not fm.get(key):
            findings.append(Finding(ERROR, subject, "frontmatter",
                                    f"missing required key `{key}` ({rel})"))

    if name and not NAME_RE.match(name):
        findings.append(Finding(ERROR, subject, "naming",
                                f"`{name}` is not kebab-case"))
    if name and name != path.parent.name:
        findings.append(Finding(ERROR, subject, "naming",
                                f"frontmatter name `{name}` != directory `{path.parent.name}` "
                                "— the runtime discovers by directory, so these must agree"))

    for key in sorted(set(fm) - SANCTIONED_KEYS):
        findings.append(Finding(WARN, subject, "portability",
                                f"unsanctioned frontmatter key `{key}` — inert in some "
                                "runtimes, so its effect is untested"))

    tokens = round(len(text.encode("utf-8")) / 4)
    if tokens > TOKEN_WARN:
        findings.append(Finding(WARN, subject, "tokens",
                                f"SKILL.md is ~{tokens} tokens (>{TOKEN_WARN}); move reference "
                                "material to a sibling file loaded on demand"))

    skill = {"name": subject, "path": rel, "tokens": tokens,
             "description": fm.get("description", ""), "body": body}
    return skill, findings


def lint_pairs(skills: list[dict]) -> tuple[list[Finding], dict[str, list[str]]]:
    """Cross-skill checks — the ones no single file review can make.

    Also returns the shared passages per pair, so a report can name what to delete
    instead of only asserting that something is wrong.
    """
    findings: list[Finding] = []
    duplicates: dict[str, list[str]] = {}
    for i, a in enumerate(skills):
        for b in skills[i + 1:]:
            bits = []
            sim = jaccard(a["description"], b["description"])
            if sim >= OVERLAP_WARN:
                bits.append(f"description overlap {sim:.2f}")

            shared = shared_passages(a["body"], b["body"])
            longest = len(shared[0].split()) if shared else 0
            if len(shared) >= DUP_RUNS_WARN or longest >= DUP_LONGEST_WARN:
                bits.append(f"{len(shared)} duplicated passage(s), longest {longest} words")

            if bits:
                subject = f"{a['name']} <-> {b['name']}"
                findings.append(Finding(WARN, subject, "overlap", ", ".join(bits)))
                if shared:
                    duplicates[subject] = shared
    return findings, duplicates


def run(root: Path, strict: bool) -> tuple[int, list[Finding], list[dict]]:
    code, findings, skills, _ = run_detailed(root, strict)
    return code, findings, skills


def run_detailed(root: Path, strict: bool) -> tuple[int, list[Finding], list[dict], dict[str, list[str]]]:
    paths = find_skills(root)
    if not paths:
        return 2, [Finding(ERROR, "-", "discovery",
                           f"no plugins/*/skills/*/SKILL.md under {root}")], [], {}
    skills, findings = [], []
    for p in paths:
        try:
            skill, found = lint_one(p, root)
        except OSError as e:
            return 2, [Finding(ERROR, p.parent.name, "io", f"cannot read: {e}")], [], {}
        skills.append(skill)
        findings.extend(found)
    pair_findings, duplicates = lint_pairs(skills)
    findings.extend(pair_findings)
    findings.sort(key=lambda f: (0 if f.level == ERROR else 1, f.subject, f.code))

    failing = {ERROR, WARN} if strict else {ERROR}
    code = 1 if any(f.level in failing for f in findings) else 0
    return code, findings, skills, duplicates


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=".", help="repository root (default: cwd)")
    ap.add_argument("--strict", action="store_true",
                    help="treat WARN as failing — the CI setting")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--show-duplicates", action="store_true",
                    help="print the shared passages behind each overlap finding, so the "
                         "report says what to delete rather than only that something is wrong")
    a = ap.parse_args(argv)

    root = Path(a.repo)
    if not root.is_dir():
        print(f"cannot determine: {root} is not a directory", file=sys.stderr)
        return 2

    code, findings, skills, duplicates = run_detailed(root, a.strict)

    if a.json:
        print(json.dumps({"exit": code,
                          "skills": [{k: v for k, v in s.items() if k != "body"} for s in skills],
                          "findings": [f.as_dict() for f in findings]}, indent=2))
        return code

    errors = sum(1 for f in findings if f.level == ERROR)
    warns = len(findings) - errors
    total = sum(s["tokens"] for s in skills)
    if findings:
        print("FINDINGS")
        for f in findings:
            print(f)
            if a.show_duplicates and f.subject in duplicates:
                for passage in duplicates[f.subject]:
                    print(f"          · {passage}")
        print()
    print(f"SUMMARY  {errors} error · {warns} warn · {len(skills)} skills · ~{total} tokens")
    if code == 0 and warns and not a.strict:
        print("         (warnings do not fail without --strict)")
    return code


if __name__ == "__main__":
    _utf8_stdio()
    raise SystemExit(main())
