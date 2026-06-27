"""Natural-language → SQL translation as a generate-validate-retry loop.

The "generate" step is injected as `sample_fn(prompt) -> str` (wired to MCP host sampling
in server.py; a stub in tests), so the loop is fully testable without a live model. The
stop criterion is deterministic: a candidate is accepted only when it extracts cleanly
AND passes the read-only validator — never "looks right." On failure the validator's error
is fed back into the next prompt.

Pure stdlib; no `mcp` import.
"""
from __future__ import annotations

import re
from typing import Callable

from .validator import validate_sql

SYSTEM_PROMPT = """\
You translate a natural-language question into ONE read-only SQLite query.

Rules:
1. Output ONLY the SQL, wrapped in a ```sql ... ``` code block. No prose.
2. Read-only only: SELECT / WITH / VALUES / EXPLAIN. Never INSERT, UPDATE, DELETE,
   CREATE, ALTER, DROP, REPLACE, ATTACH, or any write/DDL.
3. A single statement — no semicolon-separated multiples.
4. Always include a LIMIT (<= 100 rows).
5. Use only tables/columns from the schema below. Quote identifiers with spaces:
   SELECT * FROM "my table".
6. If the question cannot be answered from this schema, return a one-line SQL comment
   explaining why, followed by `SELECT NULL LIMIT 0;`.

Schema:
{schema}
"""

_RETRY = (
    "\n\nThe previous attempt was rejected: {error}\n"
    "Return a corrected read-only SQL query in a ```sql ... ``` block."
)

_FENCE = re.compile(r"```(?:sql)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)


def extract_sql(text: str) -> str | None:
    """Pull SQL from a fenced block; fall back to the first read-ish line."""
    if not text:
        return None
    m = _FENCE.search(text)
    if m:
        candidate = m.group(1).strip()
        return candidate or None
    # Fallback: a bare statement starting with a read verb.
    for chunk in text.strip().split("\n\n"):
        c = chunk.strip()
        if c[:6].upper().startswith(("SELECT", "WITH", "VALUE", "EXPLAI", "PRAGMA")):
            return c
    return None


def build_prompt(question: str, schema_context: str, error: str | None = None) -> str:
    prompt = SYSTEM_PROMPT.format(schema=schema_context) + f"\n\nQuestion: {question}\n"
    if error:
        prompt += _RETRY.format(error=error)
    return prompt


def translate(
    question: str,
    schema_context: str,
    sample_fn: Callable[[str], str],
    *,
    validate_fn: Callable[[str], tuple[bool, str | None]] = validate_sql,
    max_retries: int = 3,
) -> tuple[str | None, str | None]:
    """Return (sql, None) on success or (None, last_error) after max_retries.

    Each attempt: build prompt (with prior error fed back) -> sample_fn -> extract ->
    validate. Deterministic acceptance: extracted AND validator-passed.
    """
    error: str | None = None
    for _ in range(max(1, max_retries)):
        prompt = build_prompt(question, schema_context, error)
        try:
            response = sample_fn(prompt)
        except Exception as e:  # a sampling failure is just this attempt's error
            error = f"sampling failed: {e}"
            continue
        sql = extract_sql(response or "")
        if not sql:
            error = "no SQL code block found in the response"
            continue
        ok, verr = validate_fn(sql)
        if not ok:
            error = verr or "failed read-only validation"
            continue
        return sql, None
    return None, error
