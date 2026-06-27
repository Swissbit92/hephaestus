"""Tests for the sqlite-readonly core (validator, schema, nl) — no `mcp` needed."""
from __future__ import annotations

import sqlite3

import pytest

from sqlite_readonly import nl, schema
from sqlite_readonly.validator import enforce_limit, validate_sql


# --------------------------------------------------------------------------- validator: accepts
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM users",
        "select id from t where x = 1",
        "WITH c AS (SELECT 1) SELECT * FROM c",
        "EXPLAIN SELECT 1",
        "VALUES (1), (2)",
        'PRAGMA table_info("users")',
        "(SELECT 1)",
        "SELECT 1;",  # single trailing semicolon is fine
        "SELECT name FROM t WHERE note = 'please DELETE this'",  # keyword inside a string
        "SELECT 1 -- a comment mentioning DROP TABLE\n",  # keyword inside a comment
    ],
)
def test_validate_accepts_readonly(sql):
    ok, err = validate_sql(sql)
    assert ok, err


# --------------------------------------------------------------------------- validator: rejects
@pytest.mark.parametrize(
    "sql,needle",
    [
        ("INSERT INTO t VALUES (1)", "INSERT"),
        ("UPDATE t SET x = 1", "UPDATE"),
        ("DELETE FROM t", "DELETE"),
        ("DROP TABLE t", "DROP"),
        ("CREATE TABLE t (x)", "CREATE"),
        ("ALTER TABLE t ADD COLUMN y", "ALTER"),
        ("REPLACE INTO t VALUES (1)", "REPLACE"),
        ("ATTACH DATABASE 'x' AS y", "ATTACH"),
        ("VACUUM", "VACUUM"),
        ("SELECT 1; DROP TABLE t", "multiple statements"),
        ("SELECT 1; SELECT 2", "multiple statements"),
        ("", "empty"),
        ("HELLO WORLD", "must start with"),
    ],
)
def test_validate_rejects_writes_and_stacked(sql, needle):
    ok, err = validate_sql(sql)
    assert not ok
    assert needle.lower() in (err or "").lower()


# --------------------------------------------------------------------------- enforce_limit
def test_enforce_limit_appends_when_absent():
    out = enforce_limit("SELECT * FROM t", max_rows=100)
    assert out.rstrip().endswith("LIMIT 100")


def test_enforce_limit_caps_oversized():
    out = enforce_limit("SELECT * FROM t LIMIT 5000", max_rows=100)
    # Wrapped with an outer cap; the inner LIMIT is harmless under the outer LIMIT 100.
    assert out.rstrip().endswith("LIMIT 100") and out.lstrip().startswith("SELECT * FROM (")


def test_enforce_limit_keeps_small():
    out = enforce_limit("SELECT * FROM t LIMIT 10", max_rows=100)
    assert "LIMIT 10" in out  # inner limit preserved; outer cap is the ceiling


def test_enforce_limit_wraps_with_and_select():
    for sql in ("SELECT * FROM t", "WITH c AS (SELECT 1) SELECT * FROM c"):
        out = enforce_limit(sql, max_rows=100)
        assert out.lstrip().startswith("SELECT * FROM (") and out.rstrip().endswith("LIMIT 100")


@pytest.mark.parametrize("sql", ["PRAGMA table_info(t)", "EXPLAIN SELECT 1", "VALUES (1),(2)"])
def test_enforce_limit_skips_non_wrappable(sql):
    assert enforce_limit(sql) == sql


# --------------------------------------------------------------------------- schema render + cache
def _seed_db(path, n_tables=2):
    c = sqlite3.connect(path)
    for i in range(n_tables):
        c.execute(f"CREATE TABLE t{i} (id INTEGER PRIMARY KEY, name TEXT)")
    c.commit()
    c.close()


def test_render_context_lists_tables_and_pk():
    sch = {"users": [{"name": "id", "type": "INTEGER", "pk": True},
                     {"name": "email", "type": "TEXT", "pk": False}]}
    out = schema.render_context(sch)
    assert "users" in out and "id INTEGER PK" in out and "email TEXT" in out


def test_render_context_token_budget_truncates():
    big = {f"table_{i}": [{"name": "col", "type": "TEXT", "pk": False}] for i in range(200)}
    out = schema.render_context(big, token_budget=50)  # tiny budget
    assert "truncated" in out.lower()
    # Always renders at least one table, never all 200 under a tiny budget.
    shown = out.count("- **table_")
    assert 1 <= shown < 200


def test_schema_manager_caches_with_ttl(tmp_path):
    path = str(tmp_path / "s.db")
    _seed_db(path, n_tables=2)
    calls = {"n": 0}

    def factory():
        calls["n"] += 1
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True)

    now = {"t": 1000.0}
    mgr = schema.SchemaManager(factory, ttl=100, clock=lambda: now["t"])

    s1 = mgr.get_schema()
    assert set(s1) == {"t0", "t1"} and calls["n"] == 1
    mgr.get_schema()  # within ttl → cached
    assert calls["n"] == 1
    now["t"] += 200  # past ttl
    mgr.get_schema()
    assert calls["n"] == 2
    mgr.get_schema(force=True)  # force refresh
    assert calls["n"] == 3


# --------------------------------------------------------------------------- nl: extract
def test_extract_sql_from_fence():
    assert nl.extract_sql("here:\n```sql\nSELECT 1\n```\n") == "SELECT 1"


def test_extract_sql_bare():
    assert nl.extract_sql("SELECT 1 FROM t").startswith("SELECT 1")


def test_extract_sql_none():
    assert nl.extract_sql("I cannot help with that.") is None


# --------------------------------------------------------------------------- nl: translate loop
def test_translate_success_first_try():
    sql, err = nl.translate("count users", "schema", lambda p: "```sql\nSELECT count(*) FROM users\n```")
    assert err is None and "count(*)" in sql


def test_translate_retries_with_error_feedback():
    prompts = []

    def sample(prompt):
        prompts.append(prompt)
        # First answer is a write (rejected), second is valid.
        return "```sql\nINSERT INTO t VALUES(1)\n```" if len(prompts) == 1 else "```sql\nSELECT 1\n```"

    sql, err = nl.translate("q", "schema", sample, max_retries=3)
    assert err is None and sql == "SELECT 1"
    assert len(prompts) == 2
    assert "rejected" in prompts[1].lower()  # validator error fed back into retry


def test_translate_exhausts_on_persistent_write():
    sql, err = nl.translate("q", "schema", lambda p: "```sql\nDELETE FROM t\n```", max_retries=3)
    assert sql is None
    assert "delete" in (err or "").lower()


def test_translate_handles_no_sql():
    sql, err = nl.translate("q", "schema", lambda p: "sorry, no idea", max_retries=2)
    assert sql is None and "no sql" in (err or "").lower()


def test_translate_handles_sampling_exception():
    def boom(prompt):
        raise RuntimeError("model offline")

    sql, err = nl.translate("q", "schema", boom, max_retries=2)
    assert sql is None and "sampling failed" in (err or "").lower()
