"""Tests for dormy.mcp.tools.page_fetch — fetch_page MCP + Telegram tool."""

from __future__ import annotations

import pytest

from dormy.mcp.tools.page_fetch import (
    PageFetchResult,
    _error_result,
    _extract,
    _strip_tags,
    register,
    run_fetch_page,
)
from dormy.telegram.tools import TOOL_SCHEMAS, execute_tool


def test_strip_tags_collapses_whitespace() -> None:
    assert _strip_tags("<p>Hello\n\n  world</p>") == "Hello world"


def test_extract_pulls_title_and_meta_description() -> None:
    html = """
    <html>
      <head>
        <title>  Dormy: Your Relentless Teammate  </title>
        <meta name="description" content="AI fundraising copilot for founders.">
      </head>
      <body>
        <h1>Welcome</h1>
        <h2>Built for super founders</h2>
        <p>The body text content goes here.</p>
      </body>
    </html>
    """
    title, desc, headings, cleaned = _extract(html)
    assert title == "Dormy: Your Relentless Teammate"
    assert desc == "AI fundraising copilot for founders."
    assert "Welcome" in headings
    assert "Built for super founders" in headings
    assert "The body text content goes here." in cleaned


def test_extract_falls_back_to_og_description() -> None:
    html = """
    <head>
      <meta property="og:description" content="OG fallback wins when name=description missing.">
    </head>
    """
    _, desc, _, _ = _extract(html)
    assert desc == "OG fallback wins when name=description missing."


def test_extract_handles_no_metadata() -> None:
    html = "<html><body><p>just text</p></body></html>"
    title, desc, headings, cleaned = _extract(html)
    assert title is None
    assert desc is None
    assert headings == []
    assert "just text" in cleaned


def test_extract_dedups_repeated_headings() -> None:
    html = "<h1>Same</h1><h2>Same</h2><h1>Other</h1>"
    _, _, headings, _ = _extract(html)
    assert headings == ["Same", "Other"]


def test_error_result_marks_data_source_error() -> None:
    r = _error_result("https://x.example", "boom")
    assert r.data_source == "error"
    assert r.note == "boom"
    assert r.text == ""


@pytest.mark.asyncio
async def test_run_fetch_page_rejects_bad_scheme() -> None:
    r = await run_fetch_page("not-a-url")
    assert r.data_source == "error"
    assert "http://" in r.note


@pytest.mark.asyncio
async def test_run_fetch_page_handles_unreachable_host() -> None:
    """No DNS / unreachable should NOT raise — graceful error result."""
    r = await run_fetch_page(
        "http://this-host-does-not-exist-dormy-test.invalid",
        max_chars=500,
    )
    assert isinstance(r, PageFetchResult)
    assert r.data_source == "error"
    assert "fetch failed" in r.note or "HTTP" in r.note


def test_register_attaches_to_fastmcp() -> None:
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP(name="test")
    register(mcp)
    assert mcp is not None


def test_telegram_schemas_include_fetch_page() -> None:
    names = {t["function"]["name"] for t in TOOL_SCHEMAS}
    assert "fetch_page" in names


def test_telegram_fetch_page_schema_requires_url() -> None:
    schema = next(
        t["function"] for t in TOOL_SCHEMAS if t["function"]["name"] == "fetch_page"
    )
    assert "url" in schema["parameters"]["required"]


@pytest.mark.asyncio
async def test_execute_tool_fetch_page_routes() -> None:
    """Dispatcher must hand back a PageFetchResult.model_dump() shape."""
    result = await execute_tool(
        "fetch_page", {"url": "http://this-host-does-not-exist-dormy-test.invalid"}
    )
    assert "data_source" in result
    assert result["data_source"] == "error"
