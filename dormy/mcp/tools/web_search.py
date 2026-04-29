"""web_search — real-time web search via Tavily.

Tavily docs: https://docs.tavily.com/api-reference/endpoint/search

The shared `DORMY_TAVILY_API_KEY` is paid by Dormy (server-side, not BYOK).
Tavily's free tier covers 1k searches/month — enough for v0.1 alpha.
Bump to paid when usage exceeds.

Usage from a fundraising perspective: real-time signals on what just happened
(VC raised a fund, partner moved firms, portfolio company shipped). Pair with
`recent_funding` (structured DB) and `deep_research` (heavy synthesis) for the
full picture.

The `run_web_search()` async function is the single source of truth for the
search logic — both the MCP tool wrapper below AND `dormy.telegram.tools`
call it directly. New surfaces (Discord, WeChat, etc.) should reuse it the
same way instead of duplicating Tavily plumbing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
from loguru import logger
from pydantic import BaseModel, Field

from dormy.config import settings
from dormy.memory.hooks import from_mcp_call

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


TAVILY_ENDPOINT = "https://api.tavily.com/search"
TAVILY_TIMEOUT = httpx.Timeout(20.0)


class WebSearchHit(BaseModel):
    title: str
    url: str
    content: str = Field(description="Snippet relevant to the query")
    score: float = Field(ge=0, le=1, description="Tavily relevance score")


class WebSearchResult(BaseModel):
    query: str
    answer: str | None = Field(
        default=None,
        description="Tavily's synthesized answer (only when include_answer=true)",
    )
    hits: list[WebSearchHit]
    count: int
    data_source: str = Field(description="tavily | error")
    note: str


def _error_result(query: str, message: str) -> WebSearchResult:
    return WebSearchResult(
        query=query,
        answer=None,
        hits=[],
        count=0,
        data_source="error",
        note=message,
    )


async def run_web_search(
    query: str,
    n: int = 5,
    depth: str = "basic",
    include_answer: bool = True,
) -> WebSearchResult:
    """Execute a Tavily search and return the structured result.

    Pure executor — no MCP / observation hooks. Caller (MCP wrapper or
    Telegram bot) decides whether to fire any side-effects.
    """
    api_key = settings.tavily_api_key
    if not api_key:
        return _error_result(
            query,
            "DORMY_TAVILY_API_KEY not configured on server. "
            "Tell the user web search is not available right now.",
        )

    body = {
        "api_key": api_key,
        "query": query,
        "max_results": n,
        "search_depth": depth if depth in ("basic", "advanced") else "basic",
        "include_answer": include_answer,
        "include_raw_content": False,
    }

    try:
        async with httpx.AsyncClient(timeout=TAVILY_TIMEOUT) as client:
            resp = await client.post(TAVILY_ENDPOINT, json=body)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        logger.warning(f"tavily HTTP {e.response.status_code}: {e.response.text[:200]}")
        return _error_result(query, f"Tavily HTTP {e.response.status_code}")
    except Exception as e:
        logger.warning(f"tavily request failed: {e}")
        return _error_result(query, f"web search failed: {e}")

    raw_hits = data.get("results", []) or []
    hits = [
        WebSearchHit(
            title=h.get("title", "") or "",
            url=h.get("url", "") or "",
            content=(h.get("content", "") or "")[:600],
            score=float(h.get("score", 0.0) or 0.0),
        )
        for h in raw_hits
    ]
    return WebSearchResult(
        query=query,
        answer=(data.get("answer") or None),
        hits=hits,
        count=len(hits),
        data_source="tavily",
        note=f"Tavily {depth} search returned {len(hits)} hits.",
    )


def register(mcp: "FastMCP") -> None:
    @mcp.tool(
        description=(
            "Real-time web search via Tavily. Use for fresh signals: "
            "recent VC investments, partner moves, portfolio launches, "
            "founder takes on Twitter/LinkedIn, news from the last few days. "
            "Returns ranked snippets with URLs. For structured funding data, "
            "use recent_funding instead. For deep multi-step research, use "
            "deep_research."
        ),
    )
    async def web_search(
        query: str = Field(description="Natural-language query"),
        n: int = Field(default=5, ge=1, le=10, description="Number of hits"),
        depth: str = Field(
            default="basic",
            description="'basic' (fast, ~1s) or 'advanced' (slower, deeper)",
        ),
        include_answer: bool = Field(
            default=True,
            description="Have Tavily synthesize a one-paragraph answer",
        ),
    ) -> WebSearchResult:
        result = await run_web_search(
            query=query, n=n, depth=depth, include_answer=include_answer
        )
        from_mcp_call(
            "web_search",
            {"query": query, "n": n, "depth": depth},
            result,
        )
        return result
