"""sqlite-readonly MCP server (FastMCP).

A thin wrapper over the tested, dependency-free core: db.py (read-only connection + query
path), schema.py (cached, token-budgeted context), validator.py, nl.py. This is the only
module that imports `mcp`.

Config (all optional — zero-config by default):
  SQLITE_DB_PATH       path to a .db file to serve read-only. If unset, a bundled sample
                       database is materialized and served, so the server works out of box.
  SQLITE_MAX_ROWS      result-set cap (default 100).
  SQLITE_SCHEMA_TTL    schema cache TTL seconds (default 3600).
  SQLITE_SCHEMA_TOKENS schema-context token budget (default 2000).
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import SamplingMessage, TextContent

from . import db, nl
from .schema import SchemaManager
from .validator import validate_sql

_SAMPLE_SQL = Path(__file__).resolve().parent.parent / "sample.sql"

MAX_ROWS = int(os.environ.get("SQLITE_MAX_ROWS", "100"))
SCHEMA_TTL = int(os.environ.get("SQLITE_SCHEMA_TTL", "3600"))
SCHEMA_TOKENS = int(os.environ.get("SQLITE_SCHEMA_TOKENS", "2000"))


def _resolve_db_path() -> tuple[str, bool]:
    """Return (path, is_sample). Honors SQLITE_DB_PATH; else materializes the sample."""
    configured = os.environ.get("SQLITE_DB_PATH", "").strip()
    if configured:
        return configured, False
    dest = Path(tempfile.gettempdir()) / "whetstone-sqlite-sample.db"
    return db.materialize_sample(_SAMPLE_SQL, dest), True


DB_PATH, IS_SAMPLE = _resolve_db_path()


def _connect():
    return db.readonly_connect(DB_PATH)


# One shared read-only connection for queries; SchemaManager makes its own for introspection.
try:
    _conn = _connect()
except sqlite3.OperationalError as e:
    # mode=ro requires the file to exist; surface a diagnosable message before failing.
    print(
        f"[sqlite-readonly] failed to open database {DB_PATH!r} read-only: {e}\n"
        "  - check SQLITE_DB_PATH points to an existing .db file, or leave it unset to "
        "use the bundled sample.",
        file=sys.stderr,
    )
    raise
_schema = SchemaManager(_connect, ttl=SCHEMA_TTL, token_budget=SCHEMA_TOKENS)

mcp = FastMCP("sqlite-readonly")


@mcp.resource("schema://main")
def schema_resource() -> str:
    """The database schema as compact, token-budgeted Markdown."""
    return _schema.get_context()


@mcp.tool()
def health_check() -> dict:
    """Report server status, which database is being served, and the table count.

    Note: a healthy status means the read-only connection opened — it does not validate
    any external credentials (there are none for SQLite)."""
    tables = db.list_tables(_conn)
    return {
        "status": "healthy",
        "database": DB_PATH,
        "mode": "sample" if IS_SAMPLE else "configured",
        "read_only": True,
        "table_count": len(tables),
    }


@mcp.tool()
def list_tables() -> list[str]:
    """List the user tables in the database."""
    return db.list_tables(_conn)


@mcp.tool()
def describe_table(name: str) -> list[dict]:
    """Describe a table's columns (name, type, primary-key, not-null). `name` must be an
    existing table."""
    return db.describe_table(_conn, name)


@mcp.tool()
def read_query(sql: str) -> dict:
    """Run a single read-only SQL query and return {columns, rows, executed_sql}.

    The query is validated (read-only statements only) and capped to the row limit before
    execution; the connection is read-only regardless. Writes/DDL are rejected."""
    return db.run_query(_conn, sql, MAX_ROWS)


@mcp.tool()
async def natural_language_query(question: str, ctx: Context) -> dict:
    """Answer a natural-language question by translating it to a read-only SQL query and
    executing it. Uses the host's model (MCP sampling) to generate SQL, then validates and
    runs it. Returns {question, executed_sql, columns, rows} or {error}.

    The generate->validate->retry logic mirrors the unit-tested nl.translate(); it is
    inlined here only to bridge MCP's async sampling API."""
    schema_ctx = _schema.get_context()
    error: str | None = None
    for _ in range(3):
        prompt = nl.build_prompt(question, schema_ctx, error)
        try:
            result = await ctx.session.create_message(
                messages=[SamplingMessage(role="user", content=TextContent(type="text", text=prompt))],
                max_tokens=512,
            )
        except Exception as e:
            error = f"sampling failed: {e}"
            continue
        text = getattr(result.content, "text", "") or ""
        sql = nl.extract_sql(text)
        if not sql:
            error = "no SQL code block found in the response"
            continue
        ok, verr = validate_sql(sql)
        if not ok:
            error = verr
            continue
        out = db.run_query(_conn, sql, MAX_ROWS)
        return {"question": question, **out}
    return {"error": f"could not produce a valid read-only query: {error}"}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
