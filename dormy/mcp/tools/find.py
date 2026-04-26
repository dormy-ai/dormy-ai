"""find_investors — Inner Circle × Active VC playbook.

Three-tier return structure:

    ⭐⭐ inner_circle_active    — you know + deploying in sector now
    ⭐   inner_circle_resting   — you know, not currently deploying
    🔍  external_active         — don't know yet, needs warm intro

Data flow (Week 2 Step 2):
- Primary: Supabase `contacts` table (populated by `dormy knowledge sync`)
- Fallback: hardcoded mocks in `dormy.mcp.mocks` if DB unreachable / empty

Week 3 will add Phase A (`startups.gallery` recent rounds → true "active" cut)
and Phase C (MiroThinker deep research for Pro tier when DB is thin).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger
from pydantic import BaseModel, Field

from dormy.config import settings
from dormy.mcp.mocks import EXTERNAL_ACTIVE_VCS, INNER_CIRCLE_CONTACTS
from dormy.memory.hooks import from_mcp_call

# dormy-fundingnews is an editable sibling package that produces the Active VC feed.
# Optional import — if unavailable, external_active falls back to mock.
try:
    from dormy_fundingnews.api import get_active_vcs as _fundingnews_get_active_vcs
except Exception:  # pragma: no cover
    _fundingnews_get_active_vcs = None

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


# ---------------------------------------------------------------------------
# Response schema
# ---------------------------------------------------------------------------


class InvestorMatch(BaseModel):
    id: str
    name: str
    firm: str | None = None
    role: str
    tier: str  # inner_circle_active | inner_circle_resting | external_active
    fit_score: float = Field(ge=0, le=1)
    rationale: str
    sectors: list[str] = []
    stages: list[str] = []
    recent_activity: str | None = None
    # 🌟 Inner-only fields (null for external and Free tier):
    personal_notes: str | None = None
    warm_intro_path: str | None = None
    red_flags: str | None = None


class FindInvestorsResult(BaseModel):
    inner_circle_active: list[InvestorMatch]
    inner_circle_resting: list[InvestorMatch]
    external_active: list[InvestorMatch]
    summary: str
    data_source: str = Field(
        description="'supabase' if real DB query, 'mock' if fallback"
    )
    note: str


# ---------------------------------------------------------------------------
# Mock path (unchanged — kept as fallback)
# ---------------------------------------------------------------------------


def _filter_mock(
    contacts: list[dict], sector: str | None, stage: str | None
) -> list[dict]:
    out = []
    for c in contacts:
        if sector and sector.lower() not in [s.lower() for s in c.get("sectors", [])]:
            continue
        if stage and stage.lower() not in [s.lower() for s in c.get("stages", [])]:
            continue
        out.append(c)
    return out


def _mock_to_match(c: dict, tier: str, fit: float, rationale: str) -> InvestorMatch:
    return InvestorMatch(
        id=c["id"],
        name=c["name"],
        firm=c["firm"],
        role=c["role"],
        tier=tier,
        fit_score=fit,
        rationale=rationale,
        sectors=c.get("sectors", []),
        stages=c.get("stages", []),
        recent_activity=c.get("recent_activity"),
        personal_notes=c.get("personal_notes"),
        warm_intro_path=c.get("warm_intro_path"),
        red_flags=c.get("red_flags"),
    )


async def _build_from_mock(
    sector: str | None, stage: str | None, n: int
) -> FindInvestorsResult:
    filt_inner = _filter_mock(INNER_CIRCLE_CONTACTS, sector, stage)
    half = max(1, len(filt_inner) // 2)
    active_cut, resting_cut = filt_inner[:half], filt_inner[half:]
    rationale_active = f"Matches {sector or 'your'} sector + {stage or 'your stage'}; made a relevant check recently."
    rationale_resting = f"Matches {sector or 'your'} sector but hasn't deployed recently."

    ext_rows, ext_source = await _query_external_active(sector, stage, n)
    if ext_source == "dormy-fundingnews":
        external = [
            _mock_to_match(
                c,
                "external_active",
                0.72 - i * 0.02,
                f"Active in {sector or 'your sector'}: {c.get('recent_activity') or 'recent deal'}.",
            )
            for i, c in enumerate(ext_rows[:n])
        ]
    else:
        rationale_external = f"Actively deploying in {sector or 'your sector'} — needs warm intro (source: {ext_source})."
        external = [
            _mock_to_match(c, "external_active", 0.72 - i * 0.02, rationale_external)
            for i, c in enumerate(ext_rows[:n])
        ]

    return FindInvestorsResult(
        inner_circle_active=[
            _mock_to_match(c, "inner_circle_active", 0.94 - i * 0.02, rationale_active)
            for i, c in enumerate(active_cut[:n])
        ],
        inner_circle_resting=[
            _mock_to_match(c, "inner_circle_resting", 0.78 - i * 0.02, rationale_resting)
            for i, c in enumerate(resting_cut[:n])
        ],
        external_active=external,
        summary=(
            f"Found {len(active_cut)} ⭐⭐, {len(resting_cut)} ⭐, "
            f"{len(external)} 🔍 for sector={sector or 'any'}, stage={stage or 'any'}."
        ),
        data_source=f"mock+{ext_source}",
        note=(
            f"Inner Circle is mock (run `dormy knowledge sync` to activate Supabase). "
            f"external_active sourced from {ext_source}."
        ),
    )


# ---------------------------------------------------------------------------
# Live Supabase query path
# ---------------------------------------------------------------------------


async def _query_inner_contacts(sector: str | None, stage: str | None) -> list[dict]:
    """Query Supabase for all matching Inner Circle contacts."""
    import asyncpg  # local import — only needed on DB path

    if not settings.database_url:
        return []

    # NOTE: every MCP call opens a fresh conn. Cheap enough for v0.1; switch to
    # `dormy.db.get_pool()` when we care about latency.
    conn = await asyncpg.connect(settings.database_url, statement_cache_size=0)
    try:
        rows = await conn.fetch(
            """
            SELECT id, name, firm, role, tier, sectors, stages,
                   recent_rounds, red_flags,
                   personal_notes, warm_intro_path, email, source_path
              FROM contacts
             WHERE tier = 'inner'
               AND ($1::text IS NULL OR $1 = ANY(sectors))
               AND ($2::text IS NULL OR $2 = ANY(stages))
             ORDER BY (recent_rounds IS NOT NULL) DESC, name
            """,
            sector,
            stage,
        )
        return [dict(r) for r in rows]
    finally:
        await conn.close()


def _db_row_to_match(row: dict, tier: str, fit: float, rationale: str) -> InvestorMatch:
    def _jsonb_to_str(val) -> str | None:
        """contacts.recent_rounds / red_flags are JSONB — may come back as str | None | dict."""
        if val is None:
            return None
        if isinstance(val, str):
            # asyncpg returns jsonb as str; could be '"text"' (JSON string) or plain
            s = val.strip()
            if s.startswith('"') and s.endswith('"'):
                try:
                    import json as _json
                    return _json.loads(s)
                except Exception:
                    return s
            return s
        return str(val)

    return InvestorMatch(
        id=row.get("source_path") or str(row["id"]),
        name=row["name"],
        firm=row.get("firm"),
        role=row["role"],
        tier=tier,
        fit_score=fit,
        rationale=rationale,
        sectors=list(row.get("sectors") or []),
        stages=list(row.get("stages") or []),
        recent_activity=_jsonb_to_str(row.get("recent_rounds")),
        personal_notes=row.get("personal_notes"),
        warm_intro_path=row.get("warm_intro_path"),
        red_flags=_jsonb_to_str(row.get("red_flags")),
    )


async def _query_external_active(
    sector: str | None, stage: str | None, n: int
) -> tuple[list[dict], str]:
    """
    Pull external active VCs from the dormy-fundingnews feed (recent funding events).
    Falls back to the in-repo EXTERNAL_ACTIVE_VCS mock if the feed package is
    unavailable or errors. Returns (list_of_vcs, source_tag).
    """
    if _fundingnews_get_active_vcs is None:
        return _filter_mock(EXTERNAL_ACTIVE_VCS, sector, stage), "mock"
    try:
        vcs = await _fundingnews_get_active_vcs(
            sector=sector, stage=stage, days=90, limit=n
        )
    except Exception as e:
        logger.warning(f"dormy-fundingnews.get_active_vcs failed, falling back to mock: {e}")
        return _filter_mock(EXTERNAL_ACTIVE_VCS, sector, stage), "mock"
    if not vcs:
        return _filter_mock(EXTERNAL_ACTIVE_VCS, sector, stage), "mock-empty-feed"
    return vcs, "dormy-fundingnews"


async def _build_from_db(
    rows: list[dict], sector: str | None, stage: str | None, n: int
) -> FindInvestorsResult:
    # Split by "has recent_rounds?" — proxy for "currently active".
    # Week 3 will replace this with a join against startups.gallery rounds.
    actives = [r for r in rows if r.get("recent_rounds")]
    resting = [r for r in rows if not r.get("recent_rounds")]

    rationale_active = (
        f"Inner Circle match on {sector or 'your sector'} / {stage or 'your stage'}; "
        "has recent portfolio activity."
    )
    rationale_resting = (
        f"Inner Circle match on {sector or 'your sector'} / {stage or 'your stage'}, "
        "but no recent activity on record — long-line intro candidate."
    )

    inner_active = [
        _db_row_to_match(r, "inner_circle_active", 0.94 - i * 0.02, rationale_active)
        for i, r in enumerate(actives[:n])
    ]
    inner_resting = [
        _db_row_to_match(r, "inner_circle_resting", 0.78 - i * 0.02, rationale_resting)
        for i, r in enumerate(resting[:n])
    ]

    ext_rows, ext_source = await _query_external_active(sector, stage, n)
    if ext_source == "dormy-fundingnews":
        external = [
            _mock_to_match(
                c,
                "external_active",
                0.72 - i * 0.02,
                f"Active in {sector or 'your sector'}: {c.get('recent_activity') or 'recent deal'}.",
            )
            for i, c in enumerate(ext_rows[:n])
        ]
    else:
        external = [
            _mock_to_match(
                c,
                "external_active",
                0.72 - i * 0.02,
                f"Actively deploying in {sector or 'your sector'} — needs warm intro "
                f"(source: {ext_source}).",
            )
            for i, c in enumerate(ext_rows[:n])
        ]

    summary = (
        f"Found {len(inner_active) + len(inner_resting)} Inner Circle + "
        f"{len(external)} external for sector={sector or 'any'}, stage={stage or 'any'}. "
        f"({len(inner_active)} ⭐⭐ · {len(inner_resting)} ⭐ · {len(external)} 🔍)"
    )

    return FindInvestorsResult(
        inner_circle_active=inner_active,
        inner_circle_resting=inner_resting,
        external_active=external,
        summary=summary,
        data_source=f"supabase+{ext_source}",
        note=(
            "Inner Circle data from Supabase contacts. external_active sourced from "
            f"{ext_source} (dormy-fundingnews = live feed of recent funding events)."
        ),
    )


# ---------------------------------------------------------------------------
# MCP tool
# ---------------------------------------------------------------------------


def register(mcp: "FastMCP") -> None:
    @mcp.tool(
        description=(
            "Find matching investors using Dormy's Inner Circle × Active VC playbook. "
            "Returns three tiers: inner_circle_active (you know + recent activity), "
            "inner_circle_resting (you know, currently quiet), and external_active "
            "(unknown, needs warm intro). Inner entries include personal_notes + "
            "warm_intro_path (Pro-tier private fields). "
            "Inner tier queries live Supabase (populated by `dormy knowledge sync`); "
            "external tier still uses mock until Week 3 startups.gallery integration."
        ),
    )
    async def find_investors(
        sector: str | None = Field(
            default=None,
            description="e.g. 'ai-infra', 'fintech', 'consumer'",
        ),
        stage: str | None = Field(
            default=None,
            description="pre-seed | seed | A | B | growth",
        ),
        n: int = Field(default=5, ge=1, le=20, description="Max results per tier"),
    ) -> FindInvestorsResult:
        try:
            rows = await _query_inner_contacts(sector, stage)
            if not rows:
                logger.info("contacts table returned 0 rows — falling back to mock")
                result = await _build_from_mock(sector, stage, n)
            else:
                result = await _build_from_db(rows, sector, stage, n)
        except Exception as e:
            logger.warning(f"contacts query failed, falling back to mock: {e}")
            result = await _build_from_mock(sector, stage, n)

        from_mcp_call(
            "find_investors",
            {"sector": sector, "stage": stage, "n": n},
            result,
        )
        return result
