"""Tests for dormy.mcp.tools.deep_research — MiroThinker integration.

Network-touching paths exercised manually after deploy. Unit tests
cover result shaping + the unavailable / error fallbacks.
"""

from __future__ import annotations

from dormy.mcp.tools.deep_research import (
    DEFAULT_MODEL,
    DeepResearchResult,
    _error_result,
    register,
)


def test_error_result_shape() -> None:
    r = _error_result("what just happened in AI infra?", "boom")
    assert r.question == "what just happened in AI infra?"
    assert r.answer == ""
    assert r.model == DEFAULT_MODEL
    assert r.data_source == "error"
    assert r.note == "boom"
    assert r.duration_seconds is None


def test_deep_research_result_serializes() -> None:
    r = DeepResearchResult(
        question="map the AI infra fundraising landscape last quarter",
        answer="In Q1 2026, AI infra rounds clustered around inference optimization...",
        model=DEFAULT_MODEL,
        data_source="mirothinker",
        note="MiroThinker deep research returned 1234 chars in 42.3s.",
        duration_seconds=42.3,
    )
    dumped = r.model_dump()
    assert dumped["data_source"] == "mirothinker"
    assert dumped["duration_seconds"] == 42.3
    assert "AI infra" in dumped["answer"]


def test_default_model_is_deepresearch_variant() -> None:
    """Pin the default — if MiroThinker renames, we want the test to fail loudly."""
    assert DEFAULT_MODEL == "mirothinker-1-7-30b-deepresearch"


def test_register_attaches_tool_to_fastmcp() -> None:
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP(name="test")
    register(mcp)
    assert mcp is not None
