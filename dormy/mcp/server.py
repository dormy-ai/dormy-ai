"""Dormy MCP Server — exposes 6 tools to any MCP client.

Transport: stdio (local). HTTP/SSE transport for cloud deployment lands in Week 5.

Register with Claude Code:
    claude mcp add dormy --transport stdio \\
      -- uv run --directory /path/to/dormy-ai python -m dormy.mcp.server

Or via the convenience CLI:
    dormy mcp-serve
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from dormy import __version__
from dormy.mcp.tools import find, intro, profile, recall, scan, watch

mcp: FastMCP = FastMCP(
    name="dormy",
    instructions=(
        f"Dormy AI v{__version__} — Fundraising copilot for founders. "
        "Call dormy_profile_set first with your pitch URL, then dormy_find_investors "
        "for matches, dormy_draft_intro to compose outreach. dormy_watch_vcs sets "
        "a proactive watcher. dormy_memory_recall queries the knowledge base. "
        "[Week 2 Step 1: all tools return mock data — real backends land Week 3-4.]"
    ),
)

# Register each tool module
profile.register(mcp)
scan.register(mcp)
find.register(mcp)
intro.register(mcp)
watch.register(mcp)
recall.register(mcp)


def main() -> None:
    """Entry point — runs stdio transport."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
