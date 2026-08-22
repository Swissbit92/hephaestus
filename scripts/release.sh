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

# --- Refuse early if main will reject the push --------------------------------
# Checked BEFORE any mutation, on purpose. `main` requires status checks and enforces them
# on admins, so a freshly-created commit — which by definition has no checks yet — cannot
# be pushed directly. Discovering that after the bump and tag leaves the worst possible
# state: manifest bumped, tag created locally, nothing published, and a git error that
# says nothing about which half happened. The same failure mode the "already at $NEW"
# branch below was written to avoid.
#
# Only fires when a bump commit would actually be created. When the manifest already
# carries the target version — the normal case after the bump has been merged through a
# PR — nothing needs pushing to `main` and only the tag does, which is not protected.
# Refusing there would block the very path this message tells people to use.
if [[ "$DRY_RUN" != "1" && "$CUR" != "$NEW" ]] && command -v gh >/dev/null 2>&1; then
  _prot="$(gh api "repos/{owner}/{repo}/branches/main/protection" 2>/dev/null || true)"
  if [[ -n "$_prot" ]] \
     && grep -q '"enforce_admins"' <<<"$_prot" \
     && "$PY" -c "
import json,sys
d=json.loads(sys.stdin.read())
ctx=(d.get('required_status_checks') or {}).get('contexts') or []
adm=(d.get('enforce_admins') or {}).get('enabled')
sys.exit(0 if (ctx and adm) else 1)" <<<"$_prot"; then
    die "main requires status checks and enforces them on admins, so this script cannot
  push a release commit directly. Use the PR route instead:

    git switch -c release/${PLUGIN}-v\$NEW
    # bump plugins/$PLUGIN/.claude-plugin/plugin.json by hand
    git commit -am \"Release ${PLUGIN}-v\$NEW\" && git push -u origin HEAD
    gh pr create --base main && gh pr merge --merge   # after CI is green
    git switch main && git pull && scripts/release.sh $PLUGIN \$NEW   # tags the merged commit

  Nothing has been changed. Re-running after the merge takes the already-at-version
  branch below and tags HEAD."
  fi
fi

# --- Release gates ------------------------------------------------------------
# ADR-002 promoted check-public-safe.sh and test_seam.py from hygiene to *release gates*:
# "they are what makes the clean-room claim true rather than remembered." This script ran
# neither, so the claim was remembered. It also pushed and published seconds before CI
# started, meaning the tag was public before anything had verified the commit under it.
#
# These run before the version bump, so a failure leaves the tree exactly as it was found.
# --dry-run skips them deliberately: a preview that takes two minutes is a preview nobody
# uses, and it changes nothing anyway.
if [[ "$DRY_RUN" != "1" ]]; then
  echo "running release gates…"
  "$PY" -m pytest -q >/dev/null || die "test suite is red — no release"
  bash "$REPO_ROOT/scripts/check-public-safe.sh" >/dev/null \
    || die "check-public-safe.sh failed — a public repo must not publish private tokens"
  "$PY" "$REPO_ROOT/scripts/validate_manifests.py" >/dev/null \
    || die "manifest validation failed"
  echo "✔ suite green · public-safe clean · manifests valid"
fi

# --- Compute next version (math lives in bump_version.py, unit-tested) --------
CUR="$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$MANIFEST")"
NEW="$("$PY" "$REPO_ROOT/scripts/bump_version.py" "$CUR" "$BUMP")" || die "version bump failed"
TAG="${PLUGIN}-v$NEW"

git rev-parse "$TAG" >/dev/null 2>&1 && die "tag $TAG already exists"

# --- Release notes: commits since this plugin's last tag ---------------------
#
# Scoped by EXCLUDING sibling plugins rather than by including this plugin's directory.
# The difference is not cosmetic. A plugin's release routinely lands work outside its own
# tree — a gate in scripts/, its tests in tests/, an ADR or research note in docs/ — and a
# `-- plugins/<name>` filter cannot see any of it. Measured across the three releases
# before this change: 5 of 11 non-merge commits were dropped, including an invariant that
# lived entirely in scripts/ and a spike that lived entirely in docs/. The notes did not
# look wrong, they looked short, which is why it went unnoticed for three releases.
#
# Excluding siblings keeps the property the old filter was actually buying: releasing
# crucible must not narrate forge-unity's work.
LAST_TAG="$(git describe --tags --match "${PLUGIN}-v*" --abbrev=0 2>/dev/null || true)"
RANGE="${LAST_TAG:+$LAST_TAG..HEAD}"

PATHSPEC=(".")
for d in "$REPO_ROOT"/plugins/*/; do
  other="$(basename "$d")"
  [[ "$other" == "$PLUGIN" ]] && continue
  PATHSPEC+=(":(exclude)plugins/$other")
done

# --no-merges: a merge subject ("Merge pull request #7 from ...") tells a reader nothing
# about what shipped, and the commits it brought in are already in the range.
NOTES="$(git log ${RANGE:+"$RANGE"} --no-merges --pretty='- %s' -- "${PATHSPEC[@]}" 2>/dev/null \
         | grep -vi '^- Co-Authored' | grep -vi '^- Claude-Session' || true)"
if [[ -z "$NOTES" ]]; then
  # Say which of the two this is. "Maintenance release" reads as a deliberate choice, and
  # for three releases it was silently covering for a filter that matched nothing.
  echo "note: no commits found in ${RANGE:-history} — notes will say 'Maintenance release'" >&2
  NOTES="- Maintenance release"
fi

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

# --- Leave the integration branch level with main -----------------------------
# The version bump lands on main only, so without this dev sits one commit behind the
# moment a release completes. The next feature branch then forks from a dev with no bump,
# and the following release either conflicts or double-bumps. Observed in the wild the
# first time this script was used by a second session — a stale base manufactured by the
# release process itself, which is the exact failure `start-branch` gained a guard for.
TARGET="$(git config --get "branch.dev.integrationTarget" >/dev/null 2>&1 && echo dev || echo dev)"
if git show-ref --verify --quiet "refs/heads/$TARGET"; then
  if git merge-base --is-ancestor "$TARGET" main; then
    git branch -f "$TARGET" main
    git push -q origin "$TARGET" 2>/dev/null \
      && echo "✔ $TARGET fast-forwarded to main and pushed" \
      || echo "note: $TARGET fast-forwarded locally; push it when convenient"
  else
    # dev has commits main does not — fast-forwarding would silently discard them.
    echo "note: '$TARGET' has commits not in main; left alone. Merge main into it yourself." >&2
  fi
fi
echo "✔ released $TAG"
