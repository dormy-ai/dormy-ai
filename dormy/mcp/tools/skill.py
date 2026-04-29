"""MCP wrapper for the dormy-skills library — `list_skills` + `run_skill`.

Exposes 42 markdown-defined skills (40 GTM + 2 fundraising hybrid) as two
generic MCP tools. The pattern matches `web_search` / `recent_funding`:
this module's MCP wrappers delegate to `dormy.skills.runner.run_skill`,
which is also imported by `dormy.telegram.tools` — single executor, three
surfaces.

Discovery flow:
  1. Calling LLM invokes `list_skills(category=...)` to see candidates
  2. Picks one by name + description
  3. Invokes `run_skill(name, input)` with a paragraph of context

The single-dispatcher choice (vs one MCP tool per skill) keeps the tool
list at ~12 entries instead of ~50, and adding a new skill is just a
new `.md` in `dormy-skills/reference/` with no Python change.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from dormy.memory.hooks import from_mcp_call
from dormy.skills.registry import VALID_CATEGORIES, registry
from dormy.skills.runner import SkillResult, run_skill

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


class SkillListing(BaseModel):
    name: str
    category: str
    description: str = Field(description="Trigger-rich blurb for LLM filtering")


class SkillsCatalog(BaseModel):
    category: str | None = None
    skills: list[SkillListing]
    count: int
    available_categories: list[str]
    note: str


def _list_skills(category: str | None = None) -> SkillsCatalog:
    if category and category not in VALID_CATEGORIES:
        return SkillsCatalog(
            category=category,
            skills=[],
            count=0,
            available_categories=VALID_CATEGORIES,
            note=(
                f"Unknown category '{category}'. Valid: "
                f"{', '.join(VALID_CATEGORIES)}."
            ),
        )
    entries = (
        registry.list_by_category(category) if category else registry.list_all()
    )
    skills = [
        SkillListing(name=e.name, category=e.category, description=e.description)
        for e in entries
    ]
    note = (
        f"{len(skills)} skill(s) in category '{category}'."
        if category
        else f"{len(skills)} skill(s) across {len(VALID_CATEGORIES)} categories."
    )
    return SkillsCatalog(
        category=category,
        skills=skills,
        count=len(skills),
        available_categories=VALID_CATEGORIES,
        note=note,
    )


def register(mcp: "FastMCP") -> None:
    @mcp.tool(
        description=(
            "List available dormy skills (GTM + fundraising playbooks). Returns "
            "name + category + trigger-description for each. Filter by category: "
            "icp | copy | cro | seo | distribution | growth | strategy | "
            "foundations | fundraising. Call this first to discover relevant "
            "skills, then use run_skill to execute one."
        ),
    )
    async def list_skills(
        category: str | None = Field(
            default=None,
            description=(
                "Filter to one category. Omit for full catalog. "
                "Valid: icp, copy, cro, seo, distribution, growth, strategy, "
                "foundations, fundraising."
            ),
        ),
    ) -> SkillsCatalog:
        return _list_skills(category)

    @mcp.tool(
        description=(
            "Execute one dormy skill: loads the skill's markdown framework "
            "as system prompt and runs a single LLM completion. Use after "
            "list_skills to pick a name. Examples of `name`: 'gtm-cold-email', "
            "'gtm-page-cro', 'gtm-customer-research', 'gtm-pricing-strategy'. "
            "Pass a paragraph of context as `input` (the user's situation, "
            "target, constraints). Returns markdown."
        ),
    )
    async def run_skill_tool(
        name: str = Field(
            description="Skill slug from list_skills, e.g. 'gtm-cold-email'."
        ),
        input: str = Field(
            description=(
                "Natural-language context: the user's situation / target / "
                "constraints. Pass a full paragraph, not a 1-line query."
            ),
        ),
        model: str | None = Field(
            default=None,
            description=(
                "Optional override, e.g. 'anthropic/claude-sonnet-4-6' for "
                "complex critique. Default: claude-haiku-4-5."
            ),
        ),
    ) -> SkillResult:
        result = await run_skill(name=name, input=input, model=model)
        from_mcp_call(
            "run_skill",
            {"name": name, "input_chars": len(input), "model": model},
            result,
        )
        return result
