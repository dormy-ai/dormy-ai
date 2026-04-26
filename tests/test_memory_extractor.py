"""Unit tests for dormy.memory.extractor — parser + prompt builder.

These tests don't need DB or LLM access. End-to-end run_batch() requires
Supabase + OpenRouter and is exercised separately (manual integration test
via `dormy memory test-extract` once that CLI command lands).
"""

from __future__ import annotations

from uuid import uuid4

from dormy.memory.extractor import (
    MAX_CONTENT_CHARS,
    MAX_OBSERVATIONS_PER_BATCH,
    MAX_TAGS,
    VALID_KINDS,
    ConversationMessage,
    ExtractionInput,
    _parse_observations,
    build_extraction_prompt,
)


def _make_input(messages: list[ConversationMessage] | None = None) -> ExtractionInput:
    return ExtractionInput(
        user_id=uuid4(),
        source="telegram",
        session_id="test-session",
        messages=messages
        or [
            ConversationMessage(
                id="m1",
                role="user",
                content="I'm raising a 2M seed round, talked to Sequoia last week",
            ),
            ConversationMessage(
                id="m2",
                role="assistant",
                content="Got it. Any specific sectors?",
            ),
            ConversationMessage(
                id="m3",
                role="user",
                content="AI infra. Deeply technical, B2B SaaS.",
            ),
        ],
    )


# ---------------------------- prompt builder ----------------------------


def test_prompt_includes_all_kinds() -> None:
    prompt = build_extraction_prompt(_make_input())
    for k in VALID_KINDS:
        assert f'"{k}"' in prompt, f"missing kind: {k}"


def test_prompt_includes_message_content_and_ids() -> None:
    prompt = build_extraction_prompt(_make_input())
    assert "Sequoia" in prompt
    assert "AI infra" in prompt
    assert "(id: m1)" in prompt
    assert "(id: m3)" in prompt


def test_prompt_states_max_observations() -> None:
    prompt = build_extraction_prompt(_make_input())
    assert str(MAX_OBSERVATIONS_PER_BATCH) in prompt


def test_prompt_includes_prior_observations_when_provided() -> None:
    inp = _make_input()
    inp.prior_observations_summary = "Founder previously mentioned EU market focus"
    prompt = build_extraction_prompt(inp)
    assert "EU market focus" in prompt
    assert "Prior observations" in prompt


def test_prompt_omits_prior_section_when_empty() -> None:
    prompt = build_extraction_prompt(_make_input())
    assert "Prior observations" not in prompt


# ---------------------------- parser ----------------------------


def test_parser_handles_clean_json_array() -> None:
    raw = """[
        {"kind": "fact", "tags": ["fundraising", "seed"], "content": "Raising $2M seed", "confidence": 0.85, "source_message_ids": ["m1"]},
        {"kind": "preference", "tags": ["ai-infra"], "content": "Targets AI infra B2B", "confidence": 0.9, "source_message_ids": ["m3"]}
    ]"""
    out = _parse_observations(raw)
    assert len(out) == 2
    assert out[0].kind == "fact"
    assert out[0].tags == ["fundraising", "seed"]
    assert out[1].kind == "preference"
    assert out[1].confidence == 0.9


def test_parser_strips_code_fences() -> None:
    raw = '```json\n[{"kind":"goal","tags":["fundraise"],"content":"Close round by Q2","confidence":0.7,"source_message_ids":["m1"]}]\n```'
    out = _parse_observations(raw)
    assert len(out) == 1
    assert out[0].kind == "goal"


def test_parser_drops_invalid_kind() -> None:
    raw = '[{"kind":"random_invalid","tags":[],"content":"x","confidence":0.5,"source_message_ids":[]}]'
    out = _parse_observations(raw)
    assert len(out) == 0


def test_parser_drops_empty_content() -> None:
    raw = '[{"kind":"fact","tags":[],"content":"","confidence":0.5,"source_message_ids":[]}]'
    out = _parse_observations(raw)
    assert len(out) == 0


def test_parser_clamps_confidence_to_unit_range() -> None:
    raw = '[{"kind":"fact","tags":[],"content":"x","confidence":2.5,"source_message_ids":[]}]'
    out = _parse_observations(raw)
    assert len(out) == 1
    assert out[0].confidence == 1.0


def test_parser_handles_missing_confidence_with_default() -> None:
    raw = '[{"kind":"fact","tags":[],"content":"x","source_message_ids":[]}]'
    out = _parse_observations(raw)
    assert len(out) == 1
    assert out[0].confidence == 0.7


def test_parser_truncates_content_to_max_chars() -> None:
    long_content = "x" * (MAX_CONTENT_CHARS + 100)
    raw = f'[{{"kind":"fact","tags":[],"content":"{long_content}","confidence":0.5,"source_message_ids":[]}}]'
    out = _parse_observations(raw)
    assert len(out) == 1
    assert len(out[0].content) == MAX_CONTENT_CHARS


def test_parser_caps_tags_to_max() -> None:
    tags = [f"t{i}" for i in range(MAX_TAGS + 3)]
    tags_json = ",".join(f'"{t}"' for t in tags)
    raw = f'[{{"kind":"fact","tags":[{tags_json}],"content":"x","confidence":0.5,"source_message_ids":[]}}]'
    out = _parse_observations(raw)
    assert len(out) == 1
    assert len(out[0].tags) == MAX_TAGS


def test_parser_caps_observations_to_max_batch() -> None:
    items = [
        f'{{"kind":"fact","tags":[],"content":"obs{i}","confidence":0.5,"source_message_ids":[]}}'
        for i in range(MAX_OBSERVATIONS_PER_BATCH + 5)
    ]
    raw = "[" + ",".join(items) + "]"
    out = _parse_observations(raw)
    assert len(out) == MAX_OBSERVATIONS_PER_BATCH


def test_parser_lowercases_tags() -> None:
    raw = '[{"kind":"fact","tags":["Fundraising","SEED-Stage"],"content":"x","confidence":0.5,"source_message_ids":[]}]'
    out = _parse_observations(raw)
    assert len(out) == 1
    assert out[0].tags == ["fundraising", "seed-stage"]


def test_parser_returns_empty_for_non_json() -> None:
    raw = "Sorry, I cannot extract observations from this conversation."
    out = _parse_observations(raw)
    assert out == []


def test_parser_returns_empty_for_malformed_json() -> None:
    raw = '[{"kind":"fact", "tags": [unclosed'
    out = _parse_observations(raw)
    assert out == []


def test_parser_extracts_array_from_surrounding_text() -> None:
    raw = """Here are the observations:
[{"kind":"fact","tags":["x"],"content":"foo","confidence":0.5,"source_message_ids":["m1"]}]
Hope this helps!"""
    out = _parse_observations(raw)
    assert len(out) == 1
    assert out[0].content == "foo"
