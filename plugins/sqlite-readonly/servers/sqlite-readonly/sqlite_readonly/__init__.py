"""sqlite-readonly — a zero-config, read-only SQLite MCP server.

Pure logic (validator, schema, nl) is kept free of the `mcp` dependency so it can be
unit-tested without the SDK installed. Only `server.py` imports `mcp`.
"""
