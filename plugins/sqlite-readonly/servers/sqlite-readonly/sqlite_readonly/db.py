"""Read-only SQLite access — the PRIMARY guard (connection opened mode=ro) plus the
query path that layers the validator and row cap on top.

Pure stdlib (sqlite3); no `mcp` import, so the read-only guarantee and query path are
unit-testable directly.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .validator import enforce_limit, validate_sql

DEFAULT_MAX_ROWS = 100


def readonly_connect(path: str) -> sqlite3.Connection:
    """Open `path` strictly read-only. SQLite refuses every write on this handle — this is
    the primary enforcement layer; the validator is defense-in-depth."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def materialize_sample(sql_path: str | Path, dest: str | Path) -> str:
    """Build a sample DB from a .sql script once (idempotent). Used for the zero-config
    default so the server works with no DB configured."""
    dest = Path(dest)
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(str(dest))
        try:
            c.executescript(Path(sql_path).read_text(encoding="utf-8"))
            c.commit()
        finally:
            c.close()
    return str(dest)


def list_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows]


def describe_table(conn: sqlite3.Connection, name: str) -> list[dict[str, Any]]:
    """Column info for a table. The name is verified against sqlite_master first, so the
    PRAGMA interpolation can't be used for injection."""
    if name not in list_tables(conn):
        raise ValueError(f"unknown table: {name!r}")
    safe = name.replace('"', '""')  # escape embedded quotes in the identifier
    cols = conn.execute(f'PRAGMA table_info("{safe}")').fetchall()
    return [{"name": c[1], "type": c[2] or "", "pk": bool(c[5]), "notnull": bool(c[3])} for c in cols]


def run_query(conn: sqlite3.Connection, sql: str, max_rows: int = DEFAULT_MAX_ROWS) -> dict:
    """Validate (read-only), cap rows, execute. Raises ValueError if the validator rejects
    the statement. The read-only connection is a second backstop regardless."""
    ok, err = validate_sql(sql)
    if not ok:
        raise ValueError(f"query rejected: {err}")
    safe = enforce_limit(sql, max_rows)
    cur = conn.execute(safe)
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description] if cur.description else []
    return {"columns": cols, "rows": [list(r) for r in rows], "executed_sql": safe}
