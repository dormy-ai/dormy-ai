"""dormy_profile_set — build a founder/product profile from a URL (mock)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from dormy.memory.hooks import from_mcp_call

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


class ProfileResult(BaseModel):
    profile_id: str = Field(description="Stable id for this founder profile")
    source_url: str
    name: str
    stage: str = Field(description="pre-seed | seed | A | B | growth")
    sectors: list[str]
    product_summary: str
    note: str = Field(description="Mock warning (remove in Week 3)")


def register(mcp: "FastMCP") -> None:
    @mcp.tool(
        description=(
            "Set the active founder/product profile by scraping a pitch URL or GitHub repo. "
            "Subsequent calls to dormy_find_investors / dormy_draft_intro use this profile "
            "as implicit context. [Week 2 Step 1: returns mock — real scraping lands Week 3.]"
        ),
    )
    def dormy_profile_set(
        source_url: str = Field(
            description="Pitch page URL, founder GitHub, or product landing page"
        ),
    ) -> ProfileResult:
        result = ProfileResult(
            profile_id="mock-profile-001",
            source_url=source_url,
            name="Dormy AI (mock profile)",
            stage="pre-seed",
            sectors=["ai-infra", "dev-tools"],
            product_summary=(
                "AI fundraising copilot exposed as MCP + CLI. Inner Circle × Active VC "
                "playbook for investor matching; MiroThinker for deep research."
            ),
            note="⚠️ MOCK DATA — real scraper (Playwright + Vision) lands Week 3.",
        )
        from_mcp_call("dormy_profile_set", {"source_url": source_url}, result)
        return result
