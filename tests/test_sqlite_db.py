"""Integration + security tests for the read-only DB layer (db.py) — stdlib sqlite3 only,
no `mcp` needed. These prove the *primary* read-only guarantee (the connection), not just
the validator."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from sqlite_readonly import db


def _make_db(path, rows=3):
    c = sqlite3.connect(str(path))
    c.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
    c.executemany("INSERT INTO t (name) VALUES (?)", [(f"n{i}",) for i in range(rows)])
    c.commit()
    c.close()


def test_readonly_connection_blocks_writes_at_engine_level(tmp_path):
    p = tmp_path / "x.db"
    _make_db(p)
    conn = db.readonly_connect(str(p))
    # Reads work.
    assert conn.execute("SELECT count(*) FROM t").fetchone()[0] == 3
    # Direct write on the read-only handle is refused by SQLite itself — the primary guard.
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("INSERT INTO t (name) VALUES ('x')")


def test_run_query_returns_rows(tmp_path):
    p = tmp_path / "x.db"
    _make_db(p)
    conn = db.readonly_connect(str(p))
    out = db.run_query(conn, "SELECT id, name FROM t ORDER BY id")
    assert out["columns"] == ["id", "name"]
    assert len(out["rows"]) == 3


def test_run_query_rejects_writes_before_execution(tmp_path):
    p = tmp_path / "x.db"
    _make_db(p)
    conn = db.readonly_connect(str(p))
    for bad in ["INSERT INTO t (name) VALUES ('x')", "DELETE FROM t", "DROP TABLE t",
                "UPDATE t SET name='y'", "SELECT 1; DROP TABLE t"]:
        with pytest.raises(ValueError):
            db.run_query(conn, bad)


def test_run_query_caps_rows(tmp_path):
    p = tmp_path / "x.db"
    _make_db(p, rows=250)
    conn = db.readonly_connect(str(p))
    out = db.run_query(conn, "SELECT * FROM t", max_rows=100)
    assert len(out["rows"]) == 100
    assert "LIMIT 100" in out["executed_sql"]


def test_run_query_caps_despite_subquery_limit(tmp_path):
    # SF-1: an inner LIMIT in a subquery must not defeat the outer cap.
    p = tmp_path / "x.db"
    _make_db(p, rows=250)
    conn = db.readonly_connect(str(p))
    out = db.run_query(conn, "SELECT t.id FROM t, (SELECT 1 AS k LIMIT 1) s", max_rows=100)
    assert len(out["rows"]) == 100


def test_run_query_caps_despite_limit_in_string_literal(tmp_path):
    # SF-2: a LIMIT inside a string literal must not be mistaken for the real clause.
    p = tmp_path / "x.db"
    _make_db(p, rows=250)
    conn = db.readonly_connect(str(p))
    out = db.run_query(conn, "SELECT id, 'LIMIT 1' AS note FROM t", max_rows=100)
    assert len(out["rows"]) == 100


def test_run_query_wraps_with_cte(tmp_path):
    # Confirms the wrap is valid SQLite when the query starts with WITH.
    p = tmp_path / "x.db"
    _make_db(p, rows=5)
    conn = db.readonly_connect(str(p))
    out = db.run_query(conn, "WITH c AS (SELECT id FROM t) SELECT * FROM c ORDER BY id")
    assert len(out["rows"]) == 5


def test_describe_table_with_quote_in_name(tmp_path):
    # SF-3: a table name containing a double-quote must not crash introspection.
    p = tmp_path / "x.db"
    c = sqlite3.connect(str(p))
    c.execute('CREATE TABLE "fo""o" (a INTEGER, b TEXT)')
    c.commit()
    c.close()
    conn = db.readonly_connect(str(p))
    cols = db.describe_table(conn, 'fo"o')
    assert {col["name"] for col in cols} == {"a", "b"}


def test_writable_pragma_cannot_write_through_ro_connection(tmp_path):
    # The validator accepts PRAGMA; the mode=ro connection is the backstop for any write.
    p = tmp_path / "x.db"
    _make_db(p)
    conn = db.readonly_connect(str(p))
    try:
        conn.execute("PRAGMA writable_schema = ON")  # may no-op or raise on a ro handle
    except sqlite3.OperationalError:
        pass
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("UPDATE t SET name = 'x'")


def test_describe_table_rejects_unknown(tmp_path):
    p = tmp_path / "x.db"
    _make_db(p)
    conn = db.readonly_connect(str(p))
    assert {c["name"] for c in db.describe_table(conn, "t")} == {"id", "name"}
    with pytest.raises(ValueError):
        db.describe_table(conn, "no_such_table")


def test_materialize_sample_builds_and_is_idempotent(tmp_path):
    sql = Path(db.__file__).resolve().parent.parent / "sample.sql"
    dest = tmp_path / "sample.db"
    db.materialize_sample(sql, dest)
    assert dest.exists()
    conn = db.readonly_connect(str(dest))
    tables = db.list_tables(conn)
    assert "employees" in tables and "departments" in tables
    mtime = dest.stat().st_mtime
    db.materialize_sample(sql, dest)  # idempotent — does not rebuild
    assert dest.stat().st_mtime == mtime
