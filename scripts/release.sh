#!/usr/bin/env bash
#
# whetstone release helper.
#
# Bumps the plugin version, validates, commits, tags, pushes, and creates a
# GitHub release. The version pin in plugin.json is what actually triggers
# updates for installed users, so every release MUST bump it — this script
# keeps the manifest version and the git tag in lockstep.
#
# Usage:
#   scripts/release.sh patch            # 0.1.0 -> 0.1.1
#   scripts/release.sh minor            # 0.1.0 -> 0.2.0
#   scripts/release.sh major            # 0.1.0 -> 1.0.0
#   scripts/release.sh 1.2.3            # set an explicit version
#   scripts/release.sh patch --dry-run  # show what would happen, change nothing
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST="$REPO_ROOT/plugins/whetstone/.claude-plugin/plugin.json"
cd "$REPO_ROOT"

BUMP="${1:-}"
DRY_RUN=0
[[ "${2:-}" == "--dry-run" ]] && DRY_RUN=1

die() { echo "error: $*" >&2; exit 1; }

[[ -n "$BUMP" ]] || die "usage: scripts/release.sh <patch|minor|major|X.Y.Z> [--dry-run]"
[[ -f "$MANIFEST" ]] || die "manifest not found: $MANIFEST"
command -v python3 >/dev/null || die "python3 not found on PATH"

# --- Preconditions -----------------------------------------------------------
branch="$(git rev-parse --abbrev-ref HEAD)"
[[ "$branch" == "main" ]] || die "must be on 'main' (currently on '$branch')"
[[ -z "$(git status --porcelain)" ]] || die "working tree not clean — commit or stash first"

# --- Compute next version ----------------------------------------------------
CUR="$(python3 -c "import json;print(json.load(open('$MANIFEST'))['version'])")"
NEW="$(python3 - "$CUR" "$BUMP" <<'PY'
import sys, re
cur, bump = sys.argv[1], sys.argv[2]
if re.fullmatch(r'\d+\.\d+\.\d+', bump):
    print(bump); sys.exit(0)
try:
    major, minor, patch = (int(x) for x in cur.split('.'))
except ValueError:
    sys.stderr.write(f"current version not X.Y.Z: {cur!r}\n"); sys.exit(1)
if bump == 'major':   major, minor, patch = major + 1, 0, 0
elif bump == 'minor': minor, patch = minor + 1, 0
elif bump == 'patch': patch += 1
else: sys.stderr.write(f"invalid bump: {bump!r}\n"); sys.exit(1)
print(f"{major}.{minor}.{patch}")
PY
)"
TAG="v$NEW"

git rev-parse "$TAG" >/dev/null 2>&1 && die "tag $TAG already exists"

# --- Release notes from commits since the last tag --------------------------
LAST_TAG="$(git describe --tags --abbrev=0 2>/dev/null || true)"
RANGE="${LAST_TAG:+$LAST_TAG..HEAD}"
NOTES="$(git log $RANGE --pretty='- %s' 2>/dev/null | grep -vi '^- Co-Authored' || true)"
[[ -n "$NOTES" ]] || NOTES="- Maintenance release"

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
  claude plugin validate "$REPO_ROOT/plugins/whetstone" >/dev/null \
    && echo "✔ plugin validates" \
    || die "plugin validation failed — manifest reverted? check 'git diff'"
fi

git add "$MANIFEST"
git commit -q -m "Release $TAG"
git tag -a "$TAG" -m "whetstone $TAG"
git push -q origin main
git push -q origin "$TAG"

if command -v gh >/dev/null 2>&1; then
  gh release create "$TAG" --title "whetstone $TAG" --notes "$NOTES"
else
  echo "note: gh CLI not found — tag pushed, but GitHub release not created"
fi
echo "✔ released $TAG"
