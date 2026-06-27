#!/usr/bin/env bash
#
# Public-safety guard for the whetstone marketplace.
#
# This repo is PUBLIC. It must contain zero references to any private/employer system.
# This script greps the tracked tree for known private tokens and exits non-zero on any
# hit, so it can gate commits and releases.
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
PATTERN='roche|gxp|gamp|alcoa|21 cfr|part 11|snowflake|datamesh|data mesh manager|\brtis\b|synapse|neo4j-readonly|@emea\.|\.roche\.|gloaz|zehnder2'

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
