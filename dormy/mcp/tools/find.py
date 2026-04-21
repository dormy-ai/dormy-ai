"""dormy_find_investors — Inner Circle × Active VC playbook (mock).

Three-tier return structure mirrors the blueprint's `find_investors` algorithm:

    ⭐⭐ inner_circle_active    — you know + deploying in sector now
    ⭐   inner_circle_resting   — you know, not currently deploying
    🔍  external_active         — don't know yet, needs warm intro
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from dormy.mcp.mocks import EXTERNAL_ACTIVE_VCS, INNER_CIRCLE_CONTACTS

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


class InvestorMatch(BaseModel):
    id: str
    name: str
    firm: str
    role: str                      # vc | angel | ...
    tier: str                      # inner_circle_active | inner_circle_resting | external_active
    fit_score: float = Field(ge=0, le=1)
    rationale: str
    sectors: list[str]
    stages: list[str]
    recent_activity: str | None = None
    # 🌟 Inner-only fields (null for Free/external):
    personal_notes: str | None = None
    warm_intro_path: str | None = None
    red_flags: str | None = None


class FindInvestorsResult(BaseModel):
    inner_circle_active: list[InvestorMatch]
    inner_circle_resting: list[InvestorMatch]
    external_active: list[InvestorMatch]
    summary: str
    note: str


def _filter_by_criteria(
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


def _contact_to_match(contact: dict, tier: str, fit: float, rationale: str) -> InvestorMatch:
    """Transform a mock contact dict into the MCP response shape."""
    return InvestorMatch(
        id=contact["id"],
        name=contact["name"],
        firm=contact["firm"],
        role=contact["role"],
        tier=tier,
        fit_score=fit,
        rationale=rationale,
        sectors=contact.get("sectors", []),
        stages=contact.get("stages", []),
        recent_activity=contact.get("recent_activity"),
        personal_notes=contact.get("personal_notes"),
        warm_intro_path=contact.get("warm_intro_path"),
        red_flags=contact.get("red_flags"),
    )


def register(mcp: "FastMCP") -> None:
    @mcp.tool(
        description=(
            "Find matching investors using Dormy's Inner Circle × Active VC playbook. "
            "Returns three tiers: inner_circle_active (you know + deploying now), "
            "inner_circle_resting (you know, currently quiet), and external_active "
            "(unknown, needs warm intro). Inner-tier entries include personal_notes + "
            "warm_intro_path (Pro-tier private fields). "
            "[Week 2 Step 1: returns mock data from 5 dummy Inner Circle seeds. "
            "Real data from Supabase contacts + startups.gallery/news active VCs in Week 3.]"
        ),
    )
    def dormy_find_investors(
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
        filtered_inner = _filter_by_criteria(INNER_CIRCLE_CONTACTS, sector, stage)
        filtered_external = _filter_by_criteria(EXTERNAL_ACTIVE_VCS, sector, stage)

        # Mock the "active" cut — in reality this comes from startups.gallery/news
        # Here we simulate by splitting: first half of inner = active, second half = resting.
        half = max(1, len(filtered_inner) // 2)
        active_cut = filtered_inner[:half]
        resting_cut = filtered_inner[half:]

        rationale_active = (
            f"Matches {sector or 'your'} sector + {stage or 'your stage'}; "
            "made a relevant check in the past 90 days."
        )
        rationale_resting = (
            f"Matches {sector or 'your'} sector but hasn't deployed recently — "
            "worth keeping on the long list."
        )
        rationale_external = (
            f"Actively deploying in {sector or 'your sector'} — not yet in your network. "
            "dormy_draft_intro can craft a cold outreach."
        )

        inner_active = [
            _contact_to_match(c, "inner_circle_active", 0.94 - i * 0.02, rationale_active)
            for i, c in enumerate(active_cut[:n])
        ]
        inner_resting = [
            _contact_to_match(c, "inner_circle_resting", 0.78 - i * 0.02, rationale_resting)
            for i, c in enumerate(resting_cut[:n])
        ]
        external = [
            _contact_to_match(c, "external_active", 0.72 - i * 0.02, rationale_external)
            for i, c in enumerate(filtered_external[:n])
        ]

        total = len(inner_active) + len(inner_resting) + len(external)
        summary = (
            f"Found {total} matches for "
            f"sector={sector or 'any'}, stage={stage or 'any'}: "
            f"{len(inner_active)} ⭐⭐ active, {len(inner_resting)} ⭐ resting, "
            f"{len(external)} 🔍 external."
        )

        return FindInvestorsResult(
            inner_circle_active=inner_active,
            inner_circle_resting=inner_resting,
            external_active=external,
            summary=summary,
            note=(
                "⚠️ MOCK DATA from 5 dummy seeds. Real data (Supabase contacts + "
                "startups.gallery active VCs + MiroThinker deep research for Pro) lands Week 3."
            ),
        )
