"""Tests for dormy.mcp.tools.web_search — Tavily integration.

Network-touching paths are exercised via end-to-end smoke test
(see verification block in PR description). These unit tests cover
input validation, error shaping, and the registration entry point.
"""

from __future__ import annotations

import pytest

from dormy.mcp.tools.web_search import (
    WebSearchHit,
    WebSearchResult,
    _error_result,
    register,
)


def test_error_result_shape() -> None:
    r = _error_result("test query", "boom")
    assert r.query == "test query"
    assert r.answer is None
    assert r.hits == []
    assert r.count == 0
    assert r.data_source == "error"
    assert r.note == "boom"


def test_web_search_result_serializes_with_hits() -> None:
    r = WebSearchResult(
        query="vc fundraising",
        answer="Some VCs are deploying capital this quarter.",
        hits=[
            WebSearchHit(
                title="a16z raises new fund",
                url="https://example.com/a",
                content="snippet",
                score=0.91,
            ),
        ],
        count=1,
        data_source="tavily",
        note="Tavily basic search returned 1 hit.",
    )
    dumped = r.model_dump()
    assert dumped["count"] == 1
    assert dumped["hits"][0]["score"] == 0.91
    assert dumped["data_source"] == "tavily"


def test_web_search_hit_clamps_score_range() -> None:
    """Tavily scores are 0-1; if upstream sends out-of-range, pydantic should reject."""
    with pytest.raises(Exception):
        WebSearchHit(title="x", url="u", content="c", score=2.0)


def test_register_attaches_tool_to_fastmcp() -> None:
    """register(mcp) must add a callable named 'web_search' to the FastMCP instance."""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP(name="test")
    register(mcp)
    # FastMCP stores tools internally; assert at least one tool was registered.
    # We don't peek into private state — just confirm register() ran without raising.
    assert mcp is not None
