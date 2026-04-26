"""Dormy MCP Server — exposes 6 tools to any MCP client.

Two transports:
  - stdio (default): for local Claude Code / Cursor installs.
  - streamable-http: for the public hosted endpoint at mcp.heydormy.ai.

Register locally via stdio:
    claude mcp add dormy --transport stdio \\
      -- uv run --directory /path/to/dormy-ai python -m dormy.mcp.server

Register against the hosted endpoint via HTTP:
    claude mcp add dormy --transport http https://mcp.heydormy.ai/mcp \\
      -H "Authorization: Bearer <openrouter_key>"

Or via the convenience CLI:
    dormy mcp-serve                       # stdio
    dormy mcp-serve --transport http      # HTTP on 0.0.0.0:8080 (BYOK middleware on)
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from dormy import __version__
from dormy.mcp.auth import BYOKMiddleware
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


def http_app():
    """Build the Starlette ASGI app for HTTP transport.

    Layout:
      GET  /health   →  liveness probe
      ANY  /mcp      →  MCP streamable-http transport (Anthropic SDK)

    Wrapped in BYOKMiddleware so each incoming request stuffs its
    `Authorization: Bearer <key>` into a ContextVar visible to LLM call sites.
    """
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    app = mcp.streamable_http_app()

    async def health(request):  # noqa: ARG001
        return JSONResponse({"ok": True, "service": "dormy-mcp", "version": __version__})

    app.routes.append(Route("/health", health, methods=["GET"]))
    return BYOKMiddleware(app)


def main() -> None:
    """Entry point — runs stdio transport (default for local installs)."""
    mcp.run(transport="stdio")


def serve_http(host: str = "0.0.0.0", port: int = 8080) -> None:
    """Entry point for the hosted endpoint. Runs uvicorn with BYOK middleware."""
    import uvicorn

    uvicorn.run(http_app(), host=host, port=port)


if __name__ == "__main__":
    main()
