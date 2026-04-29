"""recent_funding — query recent funding events from Dormy's news DB.

Companion to `find_investors` (which aggregates VCs across deals).
This tool returns the deals themselves: who raised, how much, when,
who led. Sourced from dormy-fundingnews ETL pipeline (TechCrunch +
36kr + Pandaily + startups.gallery).

Why MCP and not skill: the data is server-side (Supabase), shared
across Claude Code + Telegram bot + future dashboard, and re-ingested
on a daily cron. None of that is reproducible client-side.

The `run_recent_funding()` async function is the single source of truth
for the query logic — both the MCP tool wrapper below AND
`dormy.telegram.tools` call it directly. Same pattern as web_search.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger
from pydantic import BaseModel, Field

from dormy.memory.hooks import from_mcp_call

# Editable sibling package — optional import for graceful fallback.
try:
    from dormy_fundingnews.api import (
        get_recent_funding_events as _fundingnews_get_recent,
    )
except Exception:  # pragma: no cover
    _fundingnews_get_recent = None

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


class FundingEventOut(BaseModel):
    company_name: str
    company_url: str | None = None
    country: str | None = None
    sector: str | None = None
    sub_sector: str | None = None
    round_type: str | None = None
    amount_usd: float | None = None
    valuation_usd: float | None = None
    lead_investors: list[str] = []
    other_investors: list[str] = []
    event_date: str
    source_url: str | None = None
    is_verified: bool = False


class RecentFundingResult(BaseModel):
    sector: str | None = None
    stage: str | None = None
    days: int
    events: list[FundingEventOut]
    count: int
    data_source: str = Field(description="db | unavailable | empty")
    note: str


def _empty_result(
    sector: str | None,
    stage: str | None,
    days: int,
    note: str,
    data_source: str = "empty",
) -> RecentFundingResult:
    return RecentFundingResult(
        sector=sector,
        stage=stage,
        days=days,
        events=[],
        count=0,
        data_source=data_source,
        note=note,
    )


async def run_recent_funding(
    sector: str | None = None,
    stage: str | None = None,
    days: int = 30,
    n: int = 10,
) -> RecentFundingResult:
    """Query Supabase for recent funding events.

    Pure executor — no MCP / observation hooks. Caller decides whether
    to fire side-effects.
    """
    if _fundingnews_get_recent is None:
        return _empty_result(
            sector,
            stage,
            days,
            "dormy-fundingnews not available — install editable dep.",
            data_source="unavailable",
        )

    try:
        rows = await _fundingnews_get_recent(
            sector=sector,
            stage=stage,
            days=days,
            limit=n,
        )
    except Exception as e:
        logger.warning(f"recent_funding query failed: {e}")
        return _empty_result(
            sector, stage, days, f"query failed: {e}", data_source="unavailable"
        )

    events = [
        FundingEventOut(
            company_name=r.get("company_name", ""),
            company_url=r.get("company_url"),
            country=r.get("country"),
            sector=r.get("sector"),
            sub_sector=r.get("sub_sector"),
            round_type=r.get("round_type"),
            amount_usd=r.get("amount_usd"),
            valuation_usd=r.get("valuation_usd"),
            lead_investors=r.get("lead_investors", []) or [],
            other_investors=r.get("other_investors", []) or [],
            event_date=r.get("event_date", ""),
            source_url=r.get("source_url"),
            is_verified=bool(r.get("is_verified", False)),
        )
        for r in rows
    ]
    note_bits = []
    if sector:
        note_bits.append(f"sector~{sector}")
    if stage:
        note_bits.append(f"stage={stage}")
    note_bits.append(f"days={days}")
    return RecentFundingResult(
        sector=sector,
        stage=stage,
        days=days,
        events=events,
        count=len(events),
        data_source="db" if events else "empty",
        note=(
            f"{len(events)} events ({', '.join(note_bits)})"
            if events
            else f"No events ({', '.join(note_bits)}). Try widening days or removing filters."
        ),
    )


def register(mcp: "FastMCP") -> None:
    @mcp.tool(
        description=(
            "Query recent funding rounds from Dormy's curated news database "
            "(TechCrunch + 36kr + Pandaily + startups.gallery, daily-ingested). "
            "Returns rounds matching sector/stage in the last `days` window. "
            "Use this when the user asks 'who just raised in <sector>' or "
            "'show me recent <stage> rounds'. For investor profiles aggregated "
            "across deals, use find_investors instead."
        ),
    )
    async def recent_funding(
        sector: str | None = Field(
            default=None,
            description="Loose substring match: 'AI' hits 'AI', 'AI Infra', etc.",
        ),
        stage: str | None = Field(
            default=None,
            description="Round stage: seed | a | b | c | growth | late",
        ),
        days: int = Field(
            default=30,
            ge=1,
            le=365,
            description="Look-back window",
        ),
        n: int = Field(default=10, ge=1, le=50, description="Max events"),
    ) -> RecentFundingResult:
        result = await run_recent_funding(
            sector=sector, stage=stage, days=days, n=n
        )
        from_mcp_call(
            "recent_funding",
            {"sector": sector, "stage": stage, "days": days, "n": n},
            result,
        )
        return result
