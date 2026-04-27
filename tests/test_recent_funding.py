"""Tests for dormy.mcp.tools.recent_funding.

DB-touching paths exercised via end-to-end after Railway deploy.
Unit tests cover result shapes + the unavailable / empty fallbacks.
"""

from __future__ import annotations

from dormy.mcp.tools.recent_funding import (
    FundingEventOut,
    RecentFundingResult,
    _empty_result,
    register,
)


def test_empty_result_default() -> None:
    r = _empty_result(sector=None, stage=None, days=30, note="boom")
    assert r.events == []
    assert r.count == 0
    assert r.data_source == "empty"
    assert r.note == "boom"


def test_empty_result_with_filters() -> None:
    r = _empty_result(
        sector="AI",
        stage="seed",
        days=14,
        note="db unreachable",
        data_source="unavailable",
    )
    assert r.sector == "AI"
    assert r.stage == "seed"
    assert r.days == 14
    assert r.data_source == "unavailable"


def test_recent_funding_result_serializes_with_events() -> None:
    r = RecentFundingResult(
        sector="AI",
        stage="seed",
        days=30,
        events=[
            FundingEventOut(
                company_name="Comfy",
                round_type="Series A",
                amount_usd=30_000_000.0,
                lead_investors=["Craft Ventures"],
                event_date="2026-04-27",
                source_url="https://example.com",
                is_verified=False,
            ),
        ],
        count=1,
        data_source="db",
        note="1 events (sector~AI, stage=seed, days=30)",
    )
    dumped = r.model_dump()
    assert dumped["count"] == 1
    assert dumped["events"][0]["company_name"] == "Comfy"
    assert dumped["events"][0]["amount_usd"] == 30_000_000.0
    assert dumped["data_source"] == "db"


def test_funding_event_out_optional_fields_default_to_none() -> None:
    e = FundingEventOut(company_name="X", event_date="2026-04-27")
    assert e.country is None
    assert e.sector is None
    assert e.amount_usd is None
    assert e.lead_investors == []
    assert e.is_verified is False


def test_register_attaches_tool_to_fastmcp() -> None:
    """register(mcp) must run without raising."""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP(name="test")
    register(mcp)
    assert mcp is not None
