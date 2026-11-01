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
#   scripts/release.sh <plugin> patch --prepare  # on a release branch cut off dev: bump the
#                                                # manifest, cut the changelog, make ONE commit.
#                                                # Never tags or pushes.
#
# <plugin> is a directory name under plugins/ (e.g. crucible).
#
# The route (main is protected, so a release reaches it through a PR):
#   1. git switch -c release/<plugin>-v<X.Y.Z> dev      # cut off dev, the integration branch
#   2. scripts/release.sh <plugin> <bump> --prepare      # bump + changelog cut + one commit
#   3. push, then gh pr create --base main               # review, CI green
#   4. merge it with a MERGE COMMIT, never a squash      # a squash leaves dev behind main
#   5. git switch main && git pull && scripts/release.sh <plugin> <X.Y.Z>   # tags, publishes,
#      and fast-forwards dev to main
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

die() { echo "error: $*" >&2; exit 1; }

USAGE="usage: scripts/release.sh <plugin> <patch|minor|major|X.Y.Z> [--dry-run | --prepare]"
PLUGIN="${1:-}"
BUMP="${2:-}"
DRY_RUN=0
PREPARE=0
[[ -n "$PLUGIN" ]] || die "$USAGE"
[[ -n "$BUMP" ]] || die "$USAGE"
shift 2
# An unknown flag is an error, not a no-op: `--prepar` silently ignored would fall through
# to a real release attempt.
for _arg in "$@"; do
  case "$_arg" in
    --dry-run) DRY_RUN=1 ;;
    --prepare) PREPARE=1 ;;
    *) die "unknown option '$_arg' — $USAGE" ;;
  esac
done
[[ "$DRY_RUN" == "1" && "$PREPARE" == "1" ]] && die "--prepare and --dry-run are mutually exclusive: --prepare makes the release commit, --dry-run changes nothing"

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
# The integration branch releases are cut from, as declared in .crucible/release.json
# ("from"); dev when undeclared. Read once, up here, because --prepare needs it to check the
# release branch and the post-release fast-forward below needs it to level the branch again.
# (This used to read branch.dev.integrationTarget — a key nothing writes — and printed dev
# on both arms of the conditional, so it never read anything.)
TARGET="$("$PY" -c 'import json,sys
try: print(json.load(open(sys.argv[1])).get("from") or "dev")
except Exception: print("dev")' "$REPO_ROOT/.crucible/release.json")"
if [[ "$PREPARE" == "1" ]]; then
  # --prepare is the one mutating mode that runs OFF main: it makes the release commit on a
  # branch that will be merged into main by PR.
  # Not on main, not on $TARGET itself (the ancestor check below is trivially true there, and
  # the release commit would land on the integration branch), not on a detached HEAD.
  [[ "$branch" != "main" && "$branch" != "$TARGET" && "$branch" != "HEAD" ]] \
    || die "--prepare runs on a release branch cut off '$TARGET', not on '$branch' — git switch -c release/${PLUGIN}-v<version> $TARGET"
  git rev-parse --verify --quiet "refs/heads/$TARGET" >/dev/null \
    || die "--prepare needs a local '$TARGET' branch to check this branch against (git fetch origin $TARGET:$TARGET)"
  git merge-base --is-ancestor "$TARGET" HEAD \
    || die "--prepare: '$branch' does not contain '$TARGET' — cut the release branch off '$TARGET', or merge '$TARGET' into it, so the release PR carries everything that is on '$TARGET' (in a shallow clone, run 'git fetch --unshallow' first)"
  # The check above is against the LOCAL $TARGET, which passes vacuously when it is behind
  # origin: the release PR would then omit work already merged there. Best-effort fetch (an
  # offline run just compares what it last saw), then hold the branch to origin/$TARGET too.
  git fetch -q origin "$TARGET" >/dev/null 2>&1 || true
  if git rev-parse --verify --quiet "refs/remotes/origin/$TARGET" >/dev/null; then
    git merge-base --is-ancestor "origin/$TARGET" HEAD \
      || die "--prepare: origin/$TARGET has commits '$branch' lacks (your local '$TARGET' is behind it) — update '$TARGET', then cut the release branch again or merge origin/$TARGET into this one (in a shallow clone, run 'git fetch --unshallow' first)"
  fi
# A dry run changes nothing, so it may preview from any branch (crucible's promote step runs
# it before integration has reached main); a real release must start from main.
elif [[ "$branch" != "main" ]]; then
  [[ "$DRY_RUN" == "1" ]] || die "must be on 'main' (currently on '$branch') — to prepare a release commit on a release branch, use --prepare"
  echo "note: dry run from '$branch' — a real release must be cut from 'main'" >&2
fi
[[ -z "$(git status --porcelain)" ]] || die "working tree not clean — commit or stash first"

# --- Compute next version (math lives in bump_version.py, unit-tested) --------
CUR="$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$MANIFEST")"
NEW="$("$PY" "$REPO_ROOT/scripts/bump_version.py" "$CUR" "$BUMP")" || die "version bump failed"
TAG="${PLUGIN}-v$NEW"

[[ "$PREPARE" != "1" || "$CUR" != "$NEW" ]] \
  || die "--prepare: $PLUGIN is already at $NEW, so there is no release commit to make (to tag a merged release, run without --prepare on main)"
git rev-parse "$TAG" >/dev/null 2>&1 && die "tag $TAG already exists"

# --- CHANGELOG: the release must have its own heading --------------------------
# [Unreleased] is cut into `## [<tag>] — date` as part of the release, not left to memory:
# after 0.6.3 nobody did, and 115 KB of released work ended up under one heading. Checked
# BEFORE the gates and any mutation, because it is cheap and a missing entry is the more
# likely failure than a red suite.
#
# Three cases. The heading exists (the cut was committed on the release branch, which is
# how a protected `main` gets it): nothing to do. It does not exist and this run will make
# the release commit (CUR != NEW): the cut happens below, with the manifest bump. It does
# not exist and nothing will be committed (CUR == NEW, tagging a merged commit): `main`
# cannot take a new commit, so the cut belongs on the release branch — refuse.
CL="$REPO_ROOT/scripts/changelog.py"
CUT_NEEDED=0
if "$PY" "$CL" --root "$REPO_ROOT" check "$PLUGIN" "$NEW" >/dev/null 2>&1; then
  CL_NOTE="CHANGELOG: [$TAG] heading present"
elif [[ "$CUR" != "$NEW" ]] && _why="$("$PY" "$CL" --root "$REPO_ROOT" check "$PLUGIN" "$NEW" --cuttable 2>&1)"; then
  CUT_NEEDED=1
  CL_NOTE="CHANGELOG: [Unreleased] will be cut into [$TAG] with the release commit"
else
  _why="$("$PY" "$CL" --root "$REPO_ROOT" check "$PLUGIN" "$NEW" --cuttable 2>&1 || true)"
  [[ "$CUR" == "$NEW" ]] && _why="CHANGELOG has no [$TAG] heading and this run commits nothing: cut it on the release branch (scripts/changelog.py cut $PLUGIN $NEW), merge, then re-run"
  CL_NOTE="CHANGELOG: PROBLEM — $_why"
  [[ "$DRY_RUN" == "1" ]] || die "$_why"
fi

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
if [[ "$DRY_RUN" != "1" && "$PREPARE" != "1" && "$CUR" != "$NEW" ]] && command -v gh >/dev/null 2>&1; then
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

    git switch -c release/${PLUGIN}-v$NEW $TARGET     # cut off $TARGET, not off main
    scripts/release.sh $PLUGIN $NEW --prepare         # bumps the manifest, cuts the changelog, one commit
    git push -u origin HEAD
    gh pr create --base main --head release/${PLUGIN}-v$NEW   # review, CI green
    gh pr merge --merge                               # a MERGE COMMIT — never squash (a squash leaves $TARGET behind main)
    git switch main && git pull && scripts/release.sh $PLUGIN $NEW   # tags the merged commit and levels $TARGET

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
# --prepare skips them too: it only makes the commit that goes into a PR, whose required CI
# checks run on that PR, and the run on main that tags the merged commit runs these gates
# before anything is published.
if [[ "$DRY_RUN" != "1" && "$PREPARE" != "1" ]]; then
  echo "running release gates…"
  # A missing pytest is not a red suite; saying "red" sends the releaser looking for a
  # failing test that does not exist.
  "$PY" -c "import pytest" >/dev/null 2>&1 \
    || die "pytest is not installed for $PY — set PYTHON to an interpreter that has it (the suite was not run)"
  "$PY" -m pytest -q >/dev/null || die "test suite is red — no release"
  bash "$REPO_ROOT/scripts/check-public-safe.sh" >/dev/null \
    || die "check-public-safe.sh failed — a public repo must not publish private tokens"
  "$PY" "$REPO_ROOT/scripts/validate_manifests.py" >/dev/null \
    || die "manifest validation failed"
  echo "✔ suite green · public-safe clean · manifests valid"
fi


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
         | grep -vi '^- Co-Authored' | grep -vi '^- Claude-Session' \
         | grep -v '^- Release [A-Za-z0-9_.-]*-v[0-9][A-Za-z0-9_.+-]*$' || true)"
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
echo "$CL_NOTE"
"$PY" "$CL" --root "$REPO_ROOT" report || echo "note: docs report unavailable"

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

# --prepare made its first write above (the manifest). A failure from here on used to leave a
# dirty tree and a message asking the operator to clean up. --prepare starts from a clean tree
# (checked at the top), so putting back exactly the two files it can have touched is exact; it
# is deliberately NOT `git checkout -- .`, which would also discard anything else.
fail() {
  if [[ "$PREPARE" == "1" ]]; then
    git reset -q -- "$MANIFEST" "$REPO_ROOT/CHANGELOG.md" 2>/dev/null || true
    git checkout -- "$MANIFEST" "$REPO_ROOT/CHANGELOG.md" 2>/dev/null || true
    die "$1 — the manifest and changelog were restored; nothing was committed"
  fi
  die "$1 — check 'git diff', then 'git checkout -- .' before retrying"
}

if command -v claude >/dev/null 2>&1; then
  claude plugin validate "$PLUGIN_DIR" >/dev/null \
    && echo "✔ plugin validates" \
    || fail "plugin validation failed"
fi

if [[ "$CUT_NEEDED" == "1" ]]; then
  "$PY" "$CL" --root "$REPO_ROOT" cut "$PLUGIN" "$NEW" || fail "changelog cut failed"
  git add "$REPO_ROOT/CHANGELOG.md"
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
  git commit -q -m "Release $TAG" || fail "the release commit failed (a hook?)"
fi
if [[ "$PREPARE" == "1" ]]; then
  # Stop before the tag and the push: this commit is not released until the PR carrying it
  # is merged into main and the script is re-run there.
  echo "✔ prepared $TAG on '$branch' — one commit, no tag, nothing pushed"
  echo "next: git push -u origin HEAD && gh pr create --base main --head $branch"
  echo "      merge it with a MERGE COMMIT (never squash), then on main: scripts/release.sh $PLUGIN $NEW"
  exit 0
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
# $TARGET is read from .crucible/release.json at the top of the script.
LEVEL_FAILED=0
if git show-ref --verify --quiet "refs/heads/$TARGET"; then
  if git merge-base --is-ancestor "$TARGET" main; then
    git branch -f "$TARGET" main
    git push -q origin "$TARGET" 2>/dev/null \
      && echo "✔ $TARGET fast-forwarded to main and pushed" \
      || echo "note: $TARGET fast-forwarded locally; push it when convenient"
  else
    # dev has commits main does not — fast-forwarding would silently discard them. This is
    # the one failure the dev-based route creates (dev moved after the release branch was
    # cut), so it is reported at the END as a warning with a non-zero exit, not as a note
    # followed by a tick: a quiet miss leaves dev behind main and the next release
    # double-bumps or conflicts.
    LEVEL_FAILED=1
  fi
fi
echo "✔ released $TAG"
if [[ "$LEVEL_FAILED" == "1" ]]; then
  echo "WARNING: '$TARGET' was NOT levelled with main. It has commits main does not contain (it moved after the release branch was cut), so the version bump never reached it. The release itself is published. Before anyone forks from '$TARGET', merge main into it (through a PR if it is protected), and push." >&2
  exit 1
fi
