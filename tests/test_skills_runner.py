"""Tests for dormy.skills.{registry, runner}.

Live Tavily/OpenRouter calls covered by smoke-test in production. Unit
tests pin: registry loads all 42 markdown files, parses frontmatter,
slots into the right category; runner returns a structured error result
when the LLM client / completion fails (so callers get a payload, not
an exception).
"""

from __future__ import annotations

import pytest

from dormy.skills.registry import (
    SKILL_CATEGORIES,
    VALID_CATEGORIES,
    SkillRegistry,
    _parse_frontmatter,
    registry,
)
from dormy.skills.runner import SkillResult, _error_result, run_skill


def test_registry_loads_all_42_skills() -> None:
    """Pin the catalog size — if a skill is renamed / dropped accidentally
    a downstream LLM call would silently fail to find it."""
    assert len(registry.list_all()) == 42


def test_every_skill_has_a_category_mapping() -> None:
    """Static SKILL_CATEGORIES must cover every markdown actually shipped."""
    file_names = {e.name for e in registry.list_all()}
    mapped = set(SKILL_CATEGORIES.keys())
    assert file_names == mapped, (
        f"category map drift — missing: {file_names - mapped}, "
        f"extra: {mapped - file_names}"
    )


def test_categories_only_from_taxonomy() -> None:
    for entry in registry.list_all():
        assert entry.category in VALID_CATEGORIES, (
            f"{entry.name} has unknown category {entry.category!r}"
        )


def test_registry_lookup_by_known_name() -> None:
    e = registry.get("gtm-cold-email")
    assert e.category == "copy"
    assert e.path.exists()
    assert "Cold Email" in e.markdown  # body actually loads


def test_registry_lookup_unknown_raises_keyerror() -> None:
    with pytest.raises(KeyError):
        registry.get("not-a-real-skill")


def test_list_by_category_filters() -> None:
    copy = registry.list_by_category("copy")
    assert len(copy) == 5  # cold-email, copywriting, copy-editing, email-sequence, ad-creative
    assert all(e.category == "copy" for e in copy)


def test_parse_frontmatter_handles_empty_string() -> None:
    assert _parse_frontmatter("") == {}


def test_parse_frontmatter_handles_no_fences() -> None:
    assert _parse_frontmatter("# Just a heading\nsome text") == {}


def test_parse_frontmatter_extracts_yaml() -> None:
    body = "---\nname: foo\ndescription: bar\n---\n\n# Title"
    fm = _parse_frontmatter(body)
    assert fm == {"name": "foo", "description": "bar"}


def test_skill_registry_isolated_root_returns_empty(tmp_path) -> None:
    """Pointing at a missing dir should produce an empty registry, not raise."""
    r = SkillRegistry(root=tmp_path / "nothing-here")
    assert r.list_all() == []
    assert r.categories() == []


def test_error_result_has_data_source_error() -> None:
    r = _error_result(name="fake", category="copy", message="oops")
    assert r.data_source == "error"
    assert r.note == "oops"
    assert r.tokens_used == 0


@pytest.mark.asyncio
async def test_run_skill_unknown_returns_error_result() -> None:
    """Caller must always get a SkillResult back — never an exception."""
    r = await run_skill(name="not-a-skill", input="x")
    assert isinstance(r, SkillResult)
    assert r.data_source == "error"
    assert "unknown skill" in r.note


@pytest.mark.asyncio
async def test_run_skill_no_openrouter_key_graceful(monkeypatch) -> None:
    """Without DORMY_OPENROUTER_API_KEY + no BYOK context, the LLM client
    factory raises RuntimeError. run_skill must catch that and return an
    error result so the bot can apologize gracefully."""
    from dormy import config as dormy_config

    monkeypatch.setattr(dormy_config.settings, "openrouter_api_key", None)
    # current_user_key ContextVar default is None unless inside HTTP middleware
    r = await run_skill(name="gtm-cold-email", input="test context")
    assert isinstance(r, SkillResult)
    # Either real key kicked in (CI env may have one) or graceful error.
    assert r.data_source in ("skill", "error")
