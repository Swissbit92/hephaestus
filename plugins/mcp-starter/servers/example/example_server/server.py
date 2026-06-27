"""Minimal FastMCP server demonstrating the mcp-starter pattern.

Two tools: `ping` (liveness) and `whoami` (shows that plugin config reached the server's
environment via ${user_config.api_key} -> EXAMPLE_API_KEY). Replace this with your own
tools; keep the packaging around it.
"""
from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("example")


@mcp.tool()
def ping() -> str:
    """Return 'pong' — a liveness check that the server started and is reachable."""
    return "pong"


@mcp.tool()
def whoami() -> dict:
    """Show whether plugin config was injected into the environment.

    Demonstrates the credential-injection path: plugin config `api_key` →
    `${user_config.api_key}` in plugin.json → `EXAMPLE_API_KEY` env var here. The value
    itself is never returned — only whether it is set."""
    return {"server": "example", "api_key_configured": bool(os.environ.get("EXAMPLE_API_KEY"))}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
