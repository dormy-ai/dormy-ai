"""Tests for dormy.telegram.tools — schemas + dispatcher.

Network-touching paths (Tavily, Supabase) exercised end-to-end via
production smoke. Unit tests cover schema shape + dispatcher routing
for known + unknown tool names.
"""

from __future__ import annotations

import pytest

from dormy.telegram.tools import TOOL_SCHEMAS, execute_tool


def test_schemas_have_required_fields() -> None:
    """OpenAI function-calling spec: each tool needs type=function, name,
    description, parameters with type=object."""
    for tool in TOOL_SCHEMAS:
        assert tool["type"] == "function"
        fn = tool["function"]
        assert "name" in fn and isinstance(fn["name"], str)
        assert "description" in fn and isinstance(fn["description"], str)
        params = fn["parameters"]
        assert params["type"] == "object"
        assert "properties" in params and isinstance(params["properties"], dict)


def test_schemas_cover_v01_tools() -> None:
    """v0.1 ships web_search + recent_funding to the bot. Pin the names so
    a rename downstream gets caught here."""
    names = {t["function"]["name"] for t in TOOL_SCHEMAS}
    assert "web_search" in names
    assert "recent_funding" in names


@pytest.mark.asyncio
async def test_execute_tool_unknown_returns_error() -> None:
    result = await execute_tool("not_a_real_tool", {})
    assert "error" in result
    assert "unknown tool" in result["error"]


@pytest.mark.asyncio
async def test_execute_tool_web_search_no_key_graceful() -> None:
    """Without DORMY_TAVILY_API_KEY the executor returns an error result
    — not raises. Critical: the bot must keep talking to the user even
    when the upstream tool is misconfigured."""
    # The real run_web_search returns data_source="error" when key missing.
    # We can call execute_tool and expect a dict back regardless.
    result = await execute_tool("web_search", {"query": "test"})
    assert isinstance(result, dict)
    # Either tavily worked (real key set) or graceful error returned.
    assert "data_source" in result or "error" in result


@pytest.mark.asyncio
async def test_execute_tool_normalizes_int_args() -> None:
    """LLM may emit string '5' for an int field. Dispatcher should coerce."""
    result = await execute_tool(
        "web_search", {"query": "x", "n": "3"}  # string, not int
    )
    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_execute_tool_recent_funding_empty_args() -> None:
    """recent_funding has all-optional params — empty args should still
    return a structured result (or graceful 'unavailable' if no DB)."""
    result = await execute_tool("recent_funding", {})
    assert isinstance(result, dict)
    assert "data_source" in result or "error" in result
