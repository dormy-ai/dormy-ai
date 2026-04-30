"""find_gtm — Inner Circle GTM advisors / agencies / operators / founder peers.

Companion to `find_investors`. Same shape (queries live Supabase, falls back
to an empty result if DB is unreachable), but reads from the `gtm_advisors`
table populated by `dormy knowledge sync` from `Network/GTM/*.md`.

Why a separate tool (not a `role` filter on find_investors): investor and
GTM are different funnels. Investor rows have stages + recent_rounds (funding
cycle data); GTM rows do not. Splitting at the tool boundary keeps each
query semantically tight and frees future GTM-specific fields (services,
engagement_model, pricing_tier) to live in `gtm_advisors` without polluting
contacts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger
from pydantic import BaseModel, Field

from dormy.config import settings
from dormy.memory.hooks import from_mcp_call

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


# ---------------------------------------------------------------------------
# Response schema
# ---------------------------------------------------------------------------


class GtmMatch(BaseModel):
    id: str
    name: str
    firm: str | None = None
    role: str  # gtm-advisor | operator | founder-peer
    fit_score: float = Field(ge=0, le=1)
    rationale: str
    sectors: list[str] = []
    tags: list[str] = []
    recent_activity: str | None = None
    # 🌟 Inner-only fields (Pro tier):
    personal_notes: str | None = None
    warm_intro_path: str | None = None
    red_flags: str | None = None


class FindGtmResult(BaseModel):
    inner_circle: list[GtmMatch]
    summary: str
    data_source: str = Field(description="'supabase' if real DB query, 'empty' otherwise")
    note: str


# ---------------------------------------------------------------------------
# Live Supabase query path
# ---------------------------------------------------------------------------


async def _query_gtm_advisors(
    sector: str | None,
    tag: str | None,
) -> list[dict]:
    """Query Supabase for matching Inner Circle GTM advisors."""
    import asyncpg

    if not settings.database_url:
        return []

    conn = await asyncpg.connect(settings.database_url, statement_cache_size=0)
    try:
        rows = await conn.fetch(
            """
            SELECT id, name, firm, role, tier, sectors, tags,
                   recent_activity, red_flags,
                   personal_notes, warm_intro_path, email, source_path,
                   updated_at
              FROM gtm_advisors
             WHERE tier = 'inner'
               AND ($1::text IS NULL OR $1 = ANY(sectors))
               AND ($2::text IS NULL OR $2 = ANY(tags))
             ORDER BY updated_at DESC, name
            """,
            sector,
            tag,
        )
        return [dict(r) for r in rows]
    finally:
        await conn.close()


def _jsonb_to_str(val) -> str | None:
    """gtm_advisors.recent_activity / red_flags are JSONB — may be str | None | dict."""
    if val is None:
        return None
    if isinstance(val, str):
        s = val.strip()
        if s.startswith('"') and s.endswith('"'):
            try:
                import json as _json
                return _json.loads(s)
            except Exception:
                return s
        return s
    return str(val)


def _row_to_match(row: dict, fit: float, rationale: str) -> GtmMatch:
    return GtmMatch(
        id=row.get("source_path") or str(row["id"]),
        name=row["name"],
        firm=row.get("firm"),
        role=row["role"],
        fit_score=fit,
        rationale=rationale,
        sectors=list(row.get("sectors") or []),
        tags=list(row.get("tags") or []),
        recent_activity=_jsonb_to_str(row.get("recent_activity")),
        personal_notes=row.get("personal_notes"),
        warm_intro_path=row.get("warm_intro_path"),
        red_flags=_jsonb_to_str(row.get("red_flags")),
    )


def _build_result(
    rows: list[dict],
    sector: str | None,
    tag: str | None,
    n: int,
) -> FindGtmResult:
    if not rows:
        return FindGtmResult(
            inner_circle=[],
            summary=(
                f"No Inner Circle GTM matches for sector={sector or 'any'}, "
                f"tag={tag or 'any'}. Add more contacts via `dormy-trainer "
                f"contact add --role gtm-advisor` or widen the filters."
            ),
            data_source="empty",
            note="gtm_advisors table is empty or filters matched nothing.",
        )

    rationale_template = (
        f"Inner Circle GTM match on {sector or 'your sector'}"
        + (f" / tag '{tag}'" if tag else "")
        + " — recently active in your network."
    )
    matches = [
        _row_to_match(r, fit=0.94 - i * 0.02, rationale=rationale_template)
        for i, r in enumerate(rows[:n])
    ]
    summary = (
        f"Found {len(matches)} Inner Circle GTM resource(s) for "
        f"sector={sector or 'any'}, tag={tag or 'any'}."
    )
    return FindGtmResult(
        inner_circle=matches,
        summary=summary,
        data_source="supabase",
        note=(
            "GTM data from Supabase gtm_advisors (populated by "
            "`dormy knowledge sync` from Network/GTM/*.md)."
        ),
    )


# ---------------------------------------------------------------------------
# Top-level executor — shared by MCP tool + Telegram bot
# ---------------------------------------------------------------------------


async def run_find_gtm(
    sector: str | None = None,
    tag: str | None = None,
    n: int = 5,
) -> FindGtmResult:
    """Execute find_gtm logic against the gtm_advisors table."""
    try:
        rows = await _query_gtm_advisors(sector, tag)
        result = _build_result(rows, sector, tag, n)
    except Exception as e:
        logger.warning(f"gtm_advisors query failed: {e}")
        result = FindGtmResult(
            inner_circle=[],
            summary=f"GTM query failed: {e}",
            data_source="error",
            note="DB unavailable. Tell the user the inner circle is offline.",
        )

    from_mcp_call(
        "find_gtm",
        {"sector": sector, "tag": tag, "n": n},
        result,
    )
    return result


# ---------------------------------------------------------------------------
# MCP tool
# ---------------------------------------------------------------------------


def register(mcp: "FastMCP") -> None:
    @mcp.tool(
        description=(
            "Find matching Inner Circle GTM resources — agencies, advisors, "
            "operators, and founder peers (role: gtm-advisor | operator | "
            "founder-peer). Use when the user is asking for help with launch "
            "/ content / growth / branding / UGC / pricing / hiring / dev-rel. "
            "Inner entries include personal_notes + warm_intro_path (Pro-tier "
            "private fields). Queries live Supabase (populated by "
            "`dormy knowledge sync` from Network/GTM/*.md). "
            "For investors (vc / angel) use find_investors instead."
        ),
    )
    async def find_gtm(
        sector: str | None = Field(
            default=None,
            description="Focus area, e.g. 'ai', 'consumer-tech', 'fintech'",
        ),
        tag: str | None = Field(
            default=None,
            description="Tag filter, e.g. 'ai-ugc', 'creative-agency', 'pricing'",
        ),
        n: int = Field(default=5, ge=1, le=20, description="Max results"),
    ) -> FindGtmResult:
        return await run_find_gtm(sector=sector, tag=tag, n=n)
