"""MCP server — the same detector tools, over the Model Context Protocol.

The tools defined in tools.py are exposed unchanged, so any MCP client (Claude
Desktop, Claude Code, another agent) can drive the exception monitor against a
snapshot without importing this package.

Run:
    MIDDLEWATCH_SNAPSHOT=data/out/snapshot.jsonl python -m middlewatch.mcp_server

Claude Desktop config (claude_desktop_config.json):

    {
      "mcpServers": {
        "middle-watch": {
          "command": "python",
          "args": ["-m", "middlewatch.mcp_server"],
          "cwd": "/absolute/path/to/middle-watch-agent",
          "env": {
            "MIDDLEWATCH_SNAPSHOT": "data/out/snapshot.jsonl",
            "MIDDLEWATCH_CONFIG": "config/thresholds.toml"
          }
        }
      }
    }
"""

from __future__ import annotations

import json
import os
import sys

from .config import load_config
from .tools import TOOL_SPECS, ToolSession


def build_session() -> ToolSession:
    snapshot = os.environ.get("MIDDLEWATCH_SNAPSHOT", "data/out/snapshot.jsonl")
    config_path = os.environ.get("MIDDLEWATCH_CONFIG") or None
    if not os.path.exists(snapshot):
        print(f"[middle-watch] snapshot not found: {snapshot}\n"
              f"[middle-watch] set MIDDLEWATCH_SNAPSHOT, or generate one with "
              f"`python data/generate.py`", file=sys.stderr)
    return ToolSession(snapshot, load_config(config_path))


def main() -> int:
    try:
        import asyncio

        import mcp.types as types
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
    except ImportError:
        print("the `mcp` package is required for the MCP server: pip install mcp",
              file=sys.stderr)
        return 1

    session = build_session()
    server = Server("middle-watch")

    @server.list_tools()
    async def list_tools() -> list:
        # exactly the tool specs the Claude API loop uses — one definition, two transports
        return [types.Tool(name=s["name"], description=s["description"],
                           inputSchema=s["input_schema"]) for s in TOOL_SPECS]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict | None) -> list:
        payload = session.dispatch(name, arguments or {})
        return [types.TextContent(type="text", text=json.dumps(payload, default=str))]

    async def serve() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream,
                             server.create_initialization_options())

    asyncio.run(serve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
