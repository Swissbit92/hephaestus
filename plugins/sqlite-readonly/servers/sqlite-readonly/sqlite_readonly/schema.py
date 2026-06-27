"""Schema introspection with a TTL cache and a token-budgeted Markdown rendering.

The source pattern this is adapted from had no ceiling on the rendered schema, so a large
DB could silently blow the model's context window. `render_context` here applies an
explicit budget and truncates with a visible note.

`introspect` takes a connection; `render_context` is pure (dict -> str) and trivially
testable. Pure stdlib.
"""
from __future__ import annotations

import time
from typing import Any, Callable

# Rough chars-per-token; good enough for a budget guardrail (not exact tokenization).
_CHARS_PER_TOKEN = 4


def introspect(conn) -> dict[str, list[dict[str, Any]]]:
    """Return {table_name: [{name, type, pk}, ...]} for all user tables."""
    tables: dict[str, list[dict[str, Any]]] = {}
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    for (name,) in rows:
        # PRAGMA table_info is read-only introspection; the name comes from sqlite_master
        # (not user input). Escape embedded quotes so a table named e.g. fo"o doesn't break.
        safe = name.replace('"', '""')
        cols = conn.execute(f'PRAGMA table_info("{safe}")').fetchall()
        tables[name] = [
            {"name": c[1], "type": c[2] or "", "pk": bool(c[5])} for c in cols
        ]
    return tables


def render_context(schema: dict[str, list[dict[str, Any]]], token_budget: int = 2000) -> str:
    """Render schema as compact Markdown, capped at ~token_budget tokens.

    When the full rendering would exceed the budget, tables are emitted until the budget
    is reached and a truncation note lists how many were omitted — never a silent cut.
    """
    char_budget = token_budget * _CHARS_PER_TOKEN
    lines: list[str] = ["# Database schema", ""]
    rendered = 0
    total = len(schema)
    truncated = False

    for name, cols in schema.items():
        col_strs = []
        for c in cols:
            tag = f"{c['name']} {c['type']}".strip()
            if c["pk"]:
                tag += " PK"
            col_strs.append(tag)
        line = f"- **{name}** ({', '.join(col_strs) if col_strs else 'no columns'})"
        # +1 for the newline; stop before exceeding the budget (always render >=1 table).
        projected = sum(len(x) + 1 for x in lines) + len(line) + 1
        if rendered > 0 and projected > char_budget:
            truncated = True
            break
        lines.append(line)
        rendered += 1

    if truncated:
        lines.append("")
        lines.append(
            f"_… schema truncated to fit the context budget: {rendered} of {total} "
            f"tables shown. Use `describe_table` for the rest._"
        )
    return "\n".join(lines)


class SchemaManager:
    """Caches introspected schema for `ttl` seconds. `clock` is injectable for tests."""

    def __init__(
        self,
        conn_factory: Callable[[], Any],
        ttl: int = 3600,
        token_budget: int = 2000,
        clock: Callable[[], float] = time.time,
    ):
        self._conn_factory = conn_factory
        self._ttl = ttl
        self._token_budget = token_budget
        self._clock = clock
        self._cache: dict | None = None
        self._cached_at = 0.0

    def get_schema(self, *, force: bool = False) -> dict:
        if force or self._cache is None or (self._clock() - self._cached_at) >= self._ttl:
            self._cache = introspect(self._conn_factory())
            self._cached_at = self._clock()
        return self._cache

    def get_context(self) -> str:
        return render_context(self.get_schema(), self._token_budget)
