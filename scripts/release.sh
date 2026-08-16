#!/usr/bin/env bash
#
# hephaestus marketplace release helper (multi-plugin).
#
# Bumps a plugin's version, validates, commits, tags, pushes, and creates a GitHub
# release. The version pin in plugin.json is what actually triggers updates for installed
# users, so every release MUST bump it — this script keeps the manifest version and the
# git tag in lockstep.
#
# Each plugin has its own tag namespace: <plugin>-v<version> (e.g. crucible-v0.2.0,
# sqlite-readonly-v0.1.0), so plugins version independently.
#
# Usage:
#   scripts/release.sh <plugin> patch            # 0.1.0 -> 0.1.1
#   scripts/release.sh <plugin> minor            # 0.1.0 -> 0.2.0
#   scripts/release.sh <plugin> major            # 0.1.0 -> 1.0.0
#   scripts/release.sh <plugin> 1.2.3            # set an explicit version
#   scripts/release.sh <plugin> patch --dry-run  # show what would happen, change nothing
#
# <plugin> is a directory name under plugins/ (e.g. crucible).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

die() { echo "error: $*" >&2; exit 1; }

PLUGIN="${1:-}"
BUMP="${2:-}"
DRY_RUN=0
[[ "${3:-}" == "--dry-run" ]] && DRY_RUN=1

[[ -n "$PLUGIN" ]] || die "usage: scripts/release.sh <plugin> <patch|minor|major|X.Y.Z> [--dry-run]"
[[ -n "$BUMP" ]] || die "usage: scripts/release.sh <plugin> <patch|minor|major|X.Y.Z> [--dry-run]"

PLUGIN_DIR="$REPO_ROOT/plugins/$PLUGIN"
MANIFEST="$PLUGIN_DIR/.claude-plugin/plugin.json"
[[ -d "$PLUGIN_DIR" ]] || die "plugin not found: plugins/$PLUGIN (expected a dir under plugins/)"
[[ -f "$MANIFEST" ]] || die "manifest not found: $MANIFEST"
# Resolve an interpreter that actually RUNS. `command -v python3` is not evidence on
# Windows: the name normally resolves to the Microsoft Store App Execution Alias, which
# prints an install ad, runs nothing and exits 49 — so the old guard passed and the very
# next line died. Cutting a release is exactly where a half-executed script is worst,
# since it can leave a version bumped and untagged.
. "$REPO_ROOT/scripts/checks/_python.sh"

# --- Preconditions -----------------------------------------------------------
branch="$(git rev-parse --abbrev-ref HEAD)"
[[ "$branch" == "main" ]] || die "must be on 'main' (currently on '$branch')"
[[ -z "$(git status --porcelain)" ]] || die "working tree not clean — commit or stash first"

# --- Compute next version (math lives in bump_version.py, unit-tested) --------
CUR="$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$MANIFEST")"
NEW="$("$PY" "$REPO_ROOT/scripts/bump_version.py" "$CUR" "$BUMP")" || die "version bump failed"
TAG="${PLUGIN}-v$NEW"

git rev-parse "$TAG" >/dev/null 2>&1 && die "tag $TAG already exists"

# --- Release notes: commits since this plugin's last tag, scoped to its path --
LAST_TAG="$(git describe --tags --match "${PLUGIN}-v*" --abbrev=0 2>/dev/null || true)"
RANGE="${LAST_TAG:+$LAST_TAG..HEAD}"
NOTES="$(git log ${RANGE:+"$RANGE"} --pretty='- %s' -- "plugins/$PLUGIN" 2>/dev/null | grep -vi '^- Co-Authored' || true)"
[[ -n "$NOTES" ]] || NOTES="- Maintenance release"

echo "plugin:  $PLUGIN"
echo "version: $CUR  ->  $NEW   (tag $TAG)"
echo "notes:"
echo "$NOTES" | sed 's/^/  /'

if [[ "$DRY_RUN" == "1" ]]; then
  echo "--- dry run: nothing changed ---"
  exit 0
fi

# --- Apply -------------------------------------------------------------------
# ensure_ascii=False and an explicit utf-8 encoding are both load-bearing. The default
# json.dump escapes every non-ASCII character to \uXXXX, so a single release would rewrite
# the em-dashes and typographic quotes in a plugin description into escape sequences —
# unreadable in the file, and a spurious diff on every subsequent release. Encoding is
# pinned rather than left to the platform default for the same reason the plugin scripts
# pin it: that default is cp1252 on Windows.
"$PY" - "$MANIFEST" "$NEW" <<'PY'
import json, sys
p, new = sys.argv[1], sys.argv[2]
with open(p, encoding="utf-8") as f:
    d = json.load(f)
d['version'] = new
with open(p, 'w', encoding="utf-8") as f:
    json.dump(d, f, indent=2, ensure_ascii=False)
    f.write('\n')
PY

if command -v claude >/dev/null 2>&1; then
  claude plugin validate "$PLUGIN_DIR" >/dev/null \
    && echo "✔ plugin validates" \
    || die "plugin validation failed — check 'git diff'"
fi

git add "$MANIFEST"
# The manifest is legitimately unchanged when it already carries the target version —
# a re-run after a hand-edited bump, or tagging a release whose version landed earlier.
# `git commit` exits non-zero on an empty index, and under `set -e` that aborts the run
# *before* the tag, so the release half-happens: manifest right, tag missing, and a git
# error that says nothing about which. Tag the current HEAD instead.
if git diff --cached --quiet; then
  echo "note: manifest already at $NEW — nothing to commit; tagging HEAD"
else
  git commit -q -m "Release $TAG"
fi
git tag -a "$TAG" -m "$PLUGIN $NEW"
git push -q origin main
git push -q origin "$TAG"

if command -v gh >/dev/null 2>&1; then
  gh release create "$TAG" --title "$PLUGIN $NEW" --notes "$NOTES"
else
  echo "note: gh CLI not found — tag pushed, but GitHub release not created"
fi
echo "✔ released $TAG"
