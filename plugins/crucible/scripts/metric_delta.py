#!/usr/bin/env python3
"""Did this branch ADD findings since its branch point? Duplicated code, or lint.

An absolute gate ("lint must be clean") is unusable in a codebase that already carries
findings — one repo had 2,122 at the branch point, so every branch failed and the gate was
ignored. A count gate ("do not increase the number") is blind in the other direction: fix
one finding, add a different one, and the count is unchanged. coverage_delta.py exists for
the same blindness in test counts, and this is the same fix: compare the SET of finding
identities at the current merge-base with the set now. A finding present now and absent at
the base is new, whatever happened to the total.

Because the base is re-derived each run, fixing an old finding needs no bookkeeping — the
next branch's base simply no longer has it (the ratchet is the merge-base moving forward,
not a stored file). Note that it is the *current* merge-base: after syncing the target into
the branch, findings the target fixed meanwhile are credited to it, not to this branch.

Metrics:
  clones — exact (Type-1) duplicated code: token windows of --min-tokens (default 50,
           jscpd's default) that occur more often now than at the base, reported where they
           touch lines this branch changed. Comments are stripped per language family;
           identifiers are NOT normalised, so renamed copies (Type-2) are out of scope.
           Language-agnostic by design: one tokenizer for py/sh/js/ts/java/go/c-family.
  ruff   — ruff findings keyed by (rule, file, stripped line text, occurrence), so a
           finding that merely moved lines is not new. Base side runs in a throwaway
           worktree; the user's tree is never touched.

A new clone is not automatically wrong — two similar functions can be the right call. Exit
1 means each one needs a stated reason, the way a removed test does in coverage_delta;
without a reason, the gatekeeper treats it as a REJECT.

Exit codes:
  0 — nothing new since the branch point
  1 — new findings (listed)
  2 — could not determine (no branch point, ruff missing or failing, unreadable base).
      NOT a pass.
  3 — nothing to measure (no source files of a known language). A SKIP, not a pass.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from crucible_common import (  # noqa: E402
    cache_disabled,
    cache_get,
    cache_key,
    cache_put,
    detect_target,
    script_digest,
    git_out,
    merge_base,
    run,
    utf8_stdio,
)

HASH_FAMILY = {".py", ".pyi", ".sh", ".bash", ".rb"}
SLASH_FAMILY = {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".java", ".go", ".c", ".h",
                ".cc", ".cpp", ".hpp", ".cs", ".rs", ".kt", ".swift", ".scala", ".php"}
SOURCE_EXT = HASH_FAMILY | SLASH_FAMILY
DEFAULT_MIN_TOKENS = 50

_TOKEN = re.compile(r'"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'|\w+|[^\s\w]')
_HASH_COMMENT = re.compile(r'("(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\')|#[^\n]*')
_SLASH_COMMENT = re.compile(r'("(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\')|//[^\n]*|/\*.*?\*/',
                            re.S)


class Undetermined(Exception):
    pass


# --------------------------------------------------------------------------- tokens + clones
def strip_comments(text: str, ext: str) -> str:
    """Blank out comments, keeping newlines so token line numbers stay true. Strings are
    matched first so a '#' or '//' inside one is not taken for a comment."""
    pattern = _HASH_COMMENT if ext in HASH_FAMILY else _SLASH_COMMENT

    def keep(m: re.Match) -> str:
        return m.group(1) if m.group(1) else "\n" * m.group(0).count("\n")
    return pattern.sub(keep, text)


def tokens(text: str, ext: str) -> list[tuple[str, int]]:
    out, line = [], 1
    pos = 0
    body = strip_comments(text, ext)
    for m in _TOKEN.finditer(body):
        line += body.count("\n", pos, m.start())
        pos = m.start()
        out.append((m.group(0), line))
    return out


def windows(files: dict[str, str], size: int) -> dict[str, list[tuple[str, int, int]]]:
    """window digest -> [(path, first line, last line)] for every window of `size` tokens."""
    index: dict[str, list[tuple[str, int, int]]] = defaultdict(list)
    for path, text in files.items():
        toks = tokens(text, Path(path).suffix)
        for i in range(len(toks) - size + 1):
            chunk = "\x00".join(t for t, _ in toks[i:i + size])
            digest = hashlib.blake2b(chunk.encode("utf-8"), digest_size=12).hexdigest()
            index[digest].append((path, toks[i][1], toks[i + size - 1][1]))
    return index


def new_clones(base_files: dict[str, str], head_files: dict[str, str],
               changed: dict[str, set[int]], size: int) -> list[dict]:
    """Regions of duplicated code that are new since the base and touch changed lines.

    A window is "new duplication" when it occurs at least twice now and more often than at
    the base. Overlapping windows of one paste are merged into a single region per file."""
    base_count = Counter({d: len(locs) for d, locs in windows(base_files, size).items()})
    regions: dict[str, list[list]] = defaultdict(list)
    for digest, locs in windows(head_files, size).items():
        if len(locs) < 2 or len(locs) <= base_count.get(digest, 0):
            continue
        touching = [loc for loc in locs
                    if any(n in changed.get(loc[0], ()) for n in range(loc[1], loc[2] + 1))]
        if not touching:
            continue
        for path, first, last in touching:
            # the other copies, once per file at their first line — never this window itself
            # or one overlapping it (a self-overlap is the same code, not a second copy)
            other: dict[str, int] = {}
            for p, a, b in locs:
                if p == path and a <= last and b >= first:
                    continue
                other[p] = min(other.get(p, a), a)
            regions[path].append([first, last, other])
    found = []
    for path, spans in sorted(regions.items()):
        spans.sort()
        merged = [[spans[0][0], spans[0][1], dict(spans[0][2])]]
        for first, last, others in spans[1:]:
            if first <= merged[-1][1] + 1:
                merged[-1][1] = max(merged[-1][1], last)
                for p, n in others.items():
                    merged[-1][2][p] = min(merged[-1][2].get(p, n), n)
            else:
                merged.append([first, last, dict(others)])
        for first, last, others in merged:
            found.append({"path": path, "lines": f"{first}-{last}",
                          "also_at": [f"{p}:{n}" for p, n in sorted(others.items())][:3]})
    return found


# --------------------------------------------------------------------------- git sides
def head_files(repo: Path) -> dict[str, str]:
    rc, out = run(["git", "ls-files", "-co", "--exclude-standard", "-z"], repo)
    if rc != 0:
        raise Undetermined("cannot determine: git ls-files failed")
    files = {}
    for rel in out.split("\x00"):
        if rel and Path(rel).suffix in SOURCE_EXT and (repo / rel).is_file():
            try:
                files[rel] = (repo / rel).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
    return files


def base_files(repo: Path, base: str) -> dict[str, str]:
    rc, out = run(["git", "ls-tree", "-r", "-z", "--name-only", base], repo)
    if rc != 0:
        raise Undetermined(f"cannot determine: cannot list the tree at {base[:10]}")
    paths = [p for p in out.split("\x00") if p and Path(p).suffix in SOURCE_EXT]
    if not paths:
        return {}
    try:
        proc = subprocess.run(["git", "cat-file", "--batch"], cwd=str(repo),
                              input="".join(f"{base}:{p}\n" for p in paths).encode("utf-8"),
                              capture_output=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise Undetermined(f"cannot determine: git cat-file failed ({e})") from None
    data, files, i = proc.stdout, {}, 0
    for p in paths:
        nl = data.index(b"\n", i)
        header = data[i:nl].decode("utf-8", "replace").split()
        i = nl + 1
        if len(header) < 3 or header[1] != "blob":
            continue
        size = int(header[2])
        files[p] = data[i:i + size].decode("utf-8", "replace")
        i += size + 1
    return files


def changed_lines(repo: Path, base: str, head: dict[str, str]) -> dict[str, set[int]]:
    """Lines added or modified since the base, per path. Untracked files count whole."""
    rc, out = run(["git", "diff", "-U0", "--no-color", base, "--"], repo)
    if rc != 0:
        raise Undetermined("cannot determine: git diff against the base failed")
    changed: dict[str, set[int]] = defaultdict(set)
    path = None
    for line in out.splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else None
        elif line.startswith("@@") and path:
            m = re.search(r"\+(\d+)(?:,(\d+))?", line)
            if m:
                start, count = int(m.group(1)), int(m.group(2) or 1)
                changed[path].update(range(start, start + count))
    rc, out = run(["git", "ls-files", "-o", "--exclude-standard", "-z"], repo)
    for rel in out.split("\x00") if rc == 0 else []:
        if rel in head:
            changed[rel].update(range(1, head[rel].count("\n") + 2))
    return changed


# --------------------------------------------------------------------------- ruff
def ruff_findings(root: Path, ruff: list[str]) -> set[tuple]:
    rc, out = run([*ruff, "check", "--output-format", "json", "--exit-zero", "."], root,
                  timeout=600)
    if rc == 127:
        raise Undetermined(f"cannot determine: could not run {' '.join(ruff)!r} ({out.strip()[:120]})")
    try:
        start = out.index("[")
        items = json.loads(out[start:out.rindex("]") + 1])
    except ValueError:
        raise Undetermined(f"cannot determine: ruff output was not JSON ({out.strip()[:160]})") from None
    seen: Counter = Counter()
    found = set()
    for it in items:
        try:
            rel = Path(it["filename"]).resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            rel = Path(it["filename"]).as_posix()
        row = (it.get("location") or {}).get("row", 0)
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="replace").splitlines()[row - 1].strip()
        except (OSError, IndexError):
            text = ""
        key = (it.get("code") or "?", rel, text)
        seen[key] += 1
        found.add((*key, seen[key], row, it.get("message", "")))
    return found


def ruff_delta(repo: Path, base: str, ruff: list[str], no_cache: bool = False) -> list[dict]:
    head = ruff_findings(repo, ruff)
    # The base side costs a worktree and a full lint; for one base and one ruff it is the
    # same answer every round, so it is cached. The ruff version is part of the key: a new
    # ruff can report different findings on the same code.
    rc, version = run([*ruff, "--version"], repo, timeout=60)
    key = cache_key("metric_delta.ruff.base", base, ruff, version.strip() if rc == 0 else "?",
                    script_digest(__file__))
    cached = None if cache_disabled(no_cache) else cache_get(repo, key)
    if cached is not None:
        base_keys = {tuple(k) for k in cached}
        return _new_ruff(head, base_keys)
    tmp = Path(tempfile.mkdtemp(prefix="metricdelta-"))
    wt = tmp / "base"
    rc, out = run(["git", "worktree", "add", "--detach", str(wt), base], repo)
    if rc != 0:
        shutil.rmtree(tmp, ignore_errors=True)
        raise Undetermined(f"cannot determine: could not check out the base ({out.strip()[:120]})")
    try:
        base_set = ruff_findings(wt, ruff)
    finally:
        run(["git", "worktree", "remove", "--force", str(wt)], repo)
        shutil.rmtree(tmp, ignore_errors=True)
    base_keys = {f[:4] for f in base_set}
    cache_put(repo, key, sorted(list(k) for k in base_keys))
    return _new_ruff(head, base_keys)


def _new_ruff(head: set[tuple], base_keys: set[tuple]) -> list[dict]:
    return [{"path": f[1], "lines": str(f[4]), "rule": f[0], "message": f[5]}
            for f in sorted(head, key=lambda x: (x[1], x[4])) if f[:4] not in base_keys]


# --------------------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--metric", choices=("clones", "ruff"))
    ap.add_argument("--repo", default=".")
    ap.add_argument("--target", help="integration branch (default: recorded, else detected)")
    ap.add_argument("--base", help="explicit base revision (skips merge-base)")
    ap.add_argument("--min-tokens", type=int, default=DEFAULT_MIN_TOKENS)
    ap.add_argument("--ruff", default="ruff", help="ruff command (default: ruff)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-cache", action="store_true",
                    help="recompute the base side (also CRUCIBLE_NO_CACHE=1)")
    a = ap.parse_args(argv)
    repo = Path(a.repo)
    try:
        if not a.metric:
            raise Undetermined("cannot determine: --metric clones|ruff is required")
        if git_out(repo, "rev-parse", "--git-dir") is None:
            raise Undetermined(f"cannot determine: {repo} is not a git repository")
        base = a.base
        if not base:
            target = detect_target(repo, a.target)
            if not target:
                raise Undetermined("cannot determine: no integration branch found; pass "
                                   "--target or --base")
            base = merge_base(repo, target)
            if not base:
                raise Undetermined(f"cannot determine: no merge-base with {target}")
        if a.metric == "clones":
            head = head_files(repo)
            if not head:
                print("nothing to measure: no source files of a known language.\n"
                      "This is a SKIP, not a pass.", file=sys.stderr)
                return 3
            found = new_clones(base_files(repo, base), head, changed_lines(repo, base, head),
                               a.min_tokens)
        else:
            found = ruff_delta(repo, base, a.ruff.split(), a.no_cache)
    except Undetermined as e:
        print(str(e), file=sys.stderr)
        return 2

    if a.json:
        print(json.dumps({"metric": a.metric, "base": base, "new": found}, indent=2))
    elif found:
        what = "duplicated code" if a.metric == "clones" else "ruff findings"
        print(f"NEW since the branch point ({base[:10]}): {len(found)} {what}")
        for f in found:
            extra = f" — also at {', '.join(f['also_at'])}" if f.get("also_at") else \
                f" — {f.get('rule', '')} {f.get('message', '')}"
            print(f"  + {f['path']}:{f['lines']}{extra}")
        print("Each needs a stated reason (or a fix); without one this is a REJECT.")
    else:
        print(f"OK — no new {a.metric} findings since the branch point ({base[:10]}).")
    return 1 if found else 0


if __name__ == "__main__":
    utf8_stdio()
    raise SystemExit(main())
