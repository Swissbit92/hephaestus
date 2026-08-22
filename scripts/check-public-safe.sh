#!/usr/bin/env bash
#
# Secret / employer-content guard for the hephaestus marketplace.
#
# This repo is PUBLIC, so it must contain zero references to any employer/secret system
# (the generic plugins were extracted clean-room from a private fork). This script greps the
# tracked tree for known private tokens and exits non-zero on any hit, so it can gate commits
# and releases. The generic<->domain seam is enforced separately by tests/test_seam.py.
#
# Usage:
#   scripts/check-public-safe.sh            # scan tracked files (or whole tree if not a git repo)
#   scripts/check-public-safe.sh --staged   # scan only staged changes (pre-commit use)
#
# Exit codes: 0 = clean, 1 = forbidden token found, 2 = usage/setup error.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Case-insensitive, word-ish boundaries where it helps avoid false positives.
# Add tokens here as new private sources are referenced — keep it broad.
#
# Two groups, for two different reasons:
#
#   employer     the original reason this script exists (ADR-002).
#   third-party  a private *project* whose tooling informed a plugin here. forge-unity
#                (ADR-003) generalises patterns learned in someone else's game repo, and
#                that repo is not ours to publish: its name, its teammates, its command
#                prefixes and its Photon app id must not travel with the generalisation.
#                A plugin may carry the lesson; it may not carry the project.
PATTERN='roche|gxp|gamp|alcoa|21 cfr|part 11|snowflake|datamesh|data mesh manager|\brtis\b|synapse|neo4j-readonly|@emea\.|\.roche\.|gloaz|zehnder2'
PATTERN="$PATTERN"'|schlegli|gump.bros|schleglijump|\bsgb_|sgb-team|orangutanlover|robinguedel|rgquiet'

MODE="${1:-tracked}"

scan() {
  # $1: a newline-separated list of files on stdin; greps each, prints "file:line:match"
  local hits=0
  while IFS= read -r f; do
    [[ -z "$f" ]] && continue
    [[ -f "$f" ]] || continue
    # Skip this script itself (it necessarily names the tokens).
    [[ "$f" == "scripts/check-public-safe.sh" ]] && continue
    if grep -inE "$PATTERN" "$f" >/dev/null 2>&1; then
      grep -inE "$PATTERN" "$f" | sed "s|^|$f:|"
      hits=1
    fi
  done
  return $hits
}

if [[ "$MODE" == "--staged" ]]; then
  FILES="$(git diff --cached --name-only --diff-filter=ACM 2>/dev/null || true)"
elif git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  # Tracked files plus new untracked (not gitignored) files, so additions are scanned
  # before they're ever committed.
  FILES="$(git ls-files --cached --others --exclude-standard)"
else
  FILES="$(find . -type f -not -path './.git/*')"
fi

OUTPUT="$(printf '%s\n' "$FILES" | scan || true)"

if [[ -n "$OUTPUT" ]]; then
  echo "✘ public-safety check FAILED — forbidden token(s) found:" >&2
  echo "$OUTPUT" >&2
  echo >&2
  echo "Re-author the offending content clean (patterns in, private content out) before committing." >&2
  exit 1
fi

echo "✔ public-safety check passed — no forbidden tokens"
exit 0
