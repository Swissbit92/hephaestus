#!/usr/bin/env bash
#
# whetstone marketplace release helper (multi-plugin).
#
# Bumps a plugin's version, validates, commits, tags, pushes, and creates a GitHub
# release. The version pin in plugin.json is what actually triggers updates for installed
# users, so every release MUST bump it — this script keeps the manifest version and the
# git tag in lockstep.
#
# Each plugin has its own tag namespace: <plugin>-v<version> (e.g. whetstone-v0.2.0,
# sqlite-readonly-v0.1.0), so plugins version independently.
#
# Usage:
#   scripts/release.sh <plugin> patch            # 0.1.0 -> 0.1.1
#   scripts/release.sh <plugin> minor            # 0.1.0 -> 0.2.0
#   scripts/release.sh <plugin> major            # 0.1.0 -> 1.0.0
#   scripts/release.sh <plugin> 1.2.3            # set an explicit version
#   scripts/release.sh <plugin> patch --dry-run  # show what would happen, change nothing
#
# <plugin> is a directory name under plugins/ (e.g. whetstone).
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
command -v python3 >/dev/null || die "python3 not found on PATH"

# --- Preconditions -----------------------------------------------------------
branch="$(git rev-parse --abbrev-ref HEAD)"
[[ "$branch" == "main" ]] || die "must be on 'main' (currently on '$branch')"
[[ -z "$(git status --porcelain)" ]] || die "working tree not clean — commit or stash first"

# --- Compute next version (math lives in bump_version.py, unit-tested) --------
CUR="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$MANIFEST")"
NEW="$(python3 "$REPO_ROOT/scripts/bump_version.py" "$CUR" "$BUMP")" || die "version bump failed"
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
python3 - "$MANIFEST" "$NEW" <<'PY'
import json, sys
p, new = sys.argv[1], sys.argv[2]
d = json.load(open(p))
d['version'] = new
with open(p, 'w') as f:
    json.dump(d, f, indent=2)
    f.write('\n')
PY

if command -v claude >/dev/null 2>&1; then
  claude plugin validate "$PLUGIN_DIR" >/dev/null \
    && echo "✔ plugin validates" \
    || die "plugin validation failed — check 'git diff'"
fi

git add "$MANIFEST"
git commit -q -m "Release $TAG"
git tag -a "$TAG" -m "$PLUGIN $NEW"
git push -q origin main
git push -q origin "$TAG"

if command -v gh >/dev/null 2>&1; then
  gh release create "$TAG" --title "$PLUGIN $NEW" --notes "$NOTES"
else
  echo "note: gh CLI not found — tag pushed, but GitHub release not created"
fi
echo "✔ released $TAG"
