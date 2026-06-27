"""Read-only SQL validation — defense-in-depth layer 2.

The PRIMARY read-only guard is the database connection itself (opened with
`mode=ro`, which makes SQLite refuse every write at the engine level). This module is a
deterministic second layer: it rejects statements that aren't plainly read-only *before*
they reach the connection, and caps result-set size. It is intentionally conservative —
when in doubt, reject.

Pure stdlib; no third-party imports, so it is unit-testable on its own.
"""
from __future__ import annotations

import re

# Statements must begin with one of these read-only verbs (after stripping comments/space).
_ALLOWED_STARTS = ("SELECT", "WITH", "EXPLAIN", "VALUES", "PRAGMA")

# Write / DDL / side-effecting keywords. Word-boundary matched, case-insensitive.
# PRAGMA is allowed to *start* a statement (read-only introspection like
# `PRAGMA table_info(...)`). Writable pragmas (e.g. `PRAGMA writable_schema=ON`) are NOT
# blocked here — the mode=ro connection is the backstop that refuses the resulting write.
_FORBIDDEN = [
    (r"\bINSERT\b", "INSERT"),
    (r"\bUPDATE\b", "UPDATE"),
    (r"\bDELETE\b", "DELETE"),
    (r"\bREPLACE\b", "REPLACE"),
    (r"\bDROP\b", "DROP"),
    (r"\bCREATE\b", "CREATE"),
    (r"\bALTER\b", "ALTER"),
    (r"\bTRUNCATE\b", "TRUNCATE"),
    (r"\bATTACH\b", "ATTACH"),
    (r"\bDETACH\b", "DETACH"),
    (r"\bREINDEX\b", "REINDEX"),
    (r"\bVACUUM\b", "VACUUM"),
    (r"\bUPSERT\b", "UPSERT"),
]
_FORBIDDEN_RE = [(re.compile(p, re.IGNORECASE), name) for p, name in _FORBIDDEN]

_COMMENT_LINE = re.compile(r"--[^\n]*")
_COMMENT_BLOCK = re.compile(r"/\*.*?\*/", re.DOTALL)
_STRINGS = re.compile(r"'(?:[^']|'')*'")
_DQUOTES = re.compile(r'"(?:[^"]|"")*"')


def _strip_noise(sql: str) -> str:
    """Remove comments, string literals, and double-quoted identifiers so keyword scanning
    can't be fooled by them (e.g. a column named "DELETE" or 'DROP' inside a string)."""
    s = _COMMENT_BLOCK.sub(" ", sql)
    s = _COMMENT_LINE.sub(" ", s)
    s = _STRINGS.sub("''", s)
    s = _DQUOTES.sub('""', s)
    return s


def validate_sql(sql: str) -> tuple[bool, str | None]:
    """Return (ok, error). ok=True only for a single, plainly read-only statement."""
    if not sql or not sql.strip():
        return False, "empty query"

    scan = _strip_noise(sql).strip()

    # Block stacked statements (e.g. "SELECT 1; DROP TABLE t"). A single trailing
    # semicolon is fine; anything non-trivial after it is not.
    body = scan.rstrip().rstrip(";").rstrip()
    if ";" in body:
        return False, "multiple statements are not allowed (one read-only query at a time)"

    # Forbidden-keyword scan first, so a write statement names the offending keyword
    # (e.g. "forbidden ... INSERT") rather than the generic start-verb message.
    for rx, name in _FORBIDDEN_RE:
        if rx.search(scan):
            return False, f"forbidden write/DDL keyword: {name}"

    upper = body.upper().lstrip("(")  # allow a leading paren before SELECT
    if not upper.startswith(_ALLOWED_STARTS):
        return False, (
            f"query must start with one of {', '.join(_ALLOWED_STARTS)} "
            "(read-only statements only)"
        )

    return True, None


def enforce_limit(sql: str, max_rows: int = 100) -> str:
    """Hard-cap the result set at max_rows by wrapping the query in an outer
    `SELECT * FROM (<query>) LIMIT max_rows`.

    Wrapping (rather than rewriting an inner LIMIT) makes the cap unbypassable: a LIMIT
    that lives only in a subquery, or inside a string literal, can't defeat the outer cap,
    and a smaller user-supplied LIMIT is still honored. Only SELECT/WITH are wrapped;
    PRAGMA/EXPLAIN/VALUES are returned unchanged (non-tabular or already bounded)."""
    head = _strip_noise(sql).strip().lstrip("(").upper()
    if not head.startswith(("SELECT", "WITH")):
        return sql
    core = sql.rstrip().rstrip(";").rstrip()
    # Newlines guarantee the closing paren isn't swallowed by a trailing line comment.
    return f"SELECT * FROM (\n{core}\n) LIMIT {max_rows}"
