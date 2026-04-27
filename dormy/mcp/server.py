"""Dormy MCP Server — exposes 8 tools to any MCP client.

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

import os

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from dormy import __version__
from dormy.mcp.auth import BYOKMiddleware
from dormy.mcp.tools import find, gtm, intro, profile, recall, scan, watch

# DNS rebinding protection. Default list covers local dev + Railway temp
# domain + the production custom domain. Override via env if you spin up
# another deployment (comma-separated):
#     DORMY_MCP_ALLOWED_HOSTS=mcp.heydormy.ai,foo.example.com
_DEFAULT_HOSTS = [
    "localhost",
    "127.0.0.1",
    "mcp.heydormy.ai",
    "dormy-ai-production.up.railway.app",
]
_env_hosts = os.environ.get("DORMY_MCP_ALLOWED_HOSTS")
ALLOWED_HOSTS = (
    [h.strip() for h in _env_hosts.split(",") if h.strip()]
    if _env_hosts
    else _DEFAULT_HOSTS
)

mcp: FastMCP = FastMCP(
    name="dormy",
    instructions=(
        f"Dormy AI v{__version__} — copilot for super founders, covering "
        "fundraising AND GTM. "
        "Fundraising: call profile_set first with your pitch URL, then "
        "find_investors for matches, draft_intro to compose outreach. "
        "watch_vcs sets a proactive watcher. memory_recall queries the "
        "knowledge base (Fundraising + GTM playbooks). "
        "GTM: gtm_review_landing audits a landing page (CRO/copy/SEO); "
        "gtm_draft_outreach drafts cold messages in 3 lengths. Both pull "
        "from a curated 40-skill GTM playbook corpus."
    ),
    transport_security=TransportSecuritySettings(
        # Reject hosts not in this list to prevent DNS rebinding attacks.
        allowed_hosts=ALLOWED_HOSTS,
        # Same list for browser CORS origins (with scheme).
        allowed_origins=[f"https://{h}" for h in ALLOWED_HOSTS]
        + [f"http://{h}" for h in ALLOWED_HOSTS],
    ),
)

# Register each tool module
profile.register(mcp)
scan.register(mcp)
find.register(mcp)
intro.register(mcp)
watch.register(mcp)
recall.register(mcp)
gtm.register(mcp)


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
