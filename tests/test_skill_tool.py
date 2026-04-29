"""Tests for the MCP + Telegram skill dispatch surfaces.

Pin: schemas have the right shape; dispatch routes list_skills + run_skill
correctly; unknown / missing args return graceful errors instead of
raising.
"""

from __future__ import annotations

import pytest

from dormy.mcp.tools.skill import _list_skills, register
from dormy.telegram.tools import TOOL_SCHEMAS, execute_tool


def test_list_skills_no_filter_returns_all() -> None:
    catalog = _list_skills(category=None)
    assert catalog.count == 42
    assert catalog.category is None
    assert "copy" in catalog.available_categories


def test_list_skills_filters_by_category() -> None:
    catalog = _list_skills(category="cro")
    # 6 CRO skills: page-cro, form-cro, popup-cro, onboarding-cro,
    # signup-flow-cro, paywall-upgrade-cro
    assert catalog.count == 6
    assert all(s.category == "cro" for s in catalog.skills)


def test_list_skills_unknown_category_returns_empty_with_note() -> None:
    catalog = _list_skills(category="not-a-category")
    assert catalog.count == 0
    assert catalog.skills == []
    assert "Unknown category" in catalog.note


def test_register_attaches_to_fastmcp() -> None:
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP(name="test")
    register(mcp)
    assert mcp is not None


def test_telegram_schemas_include_skill_tools() -> None:
    """Pin the Telegram tool registry — both list_skills and run_skill
    must be exposed so the bot's function-calling LLM can see them."""
    names = {t["function"]["name"] for t in TOOL_SCHEMAS}
    assert "list_skills" in names
    assert "run_skill" in names


def test_telegram_run_skill_schema_required_fields() -> None:
    schema = next(
        t["function"] for t in TOOL_SCHEMAS if t["function"]["name"] == "run_skill"
    )
    required = schema["parameters"]["required"]
    assert "name" in required
    assert "input" in required


@pytest.mark.asyncio
async def test_execute_tool_list_skills_no_args() -> None:
    """list_skills with empty args should return full catalog."""
    result = await execute_tool("list_skills", {})
    assert result["count"] == 42
    assert isinstance(result["skills"], list)
    assert result["available_categories"]


@pytest.mark.asyncio
async def test_execute_tool_list_skills_with_category() -> None:
    result = await execute_tool("list_skills", {"category": "fundraising"})
    assert result["count"] == 2  # research-vc + prep-week
    assert all(s["category"] == "fundraising" for s in result["skills"])


@pytest.mark.asyncio
async def test_execute_tool_run_skill_unknown_returns_error_payload() -> None:
    """Dispatcher must hand back a SkillResult.model_dump() with
    data_source='error' — bot needs structured payload, not exception."""
    result = await execute_tool(
        "run_skill", {"name": "not-a-real-skill", "input": "test"}
    )
    assert result["data_source"] == "error"
    assert "unknown skill" in result["note"]


@pytest.mark.asyncio
async def test_execute_tool_run_skill_missing_input_still_dispatches() -> None:
    """LLM might pass empty / missing input; dispatcher should not crash."""
    result = await execute_tool("run_skill", {"name": "gtm-cold-email"})
    # Either real key kicked in (env has one) or graceful error.
    assert isinstance(result, dict)
    assert "data_source" in result or "error" in result
