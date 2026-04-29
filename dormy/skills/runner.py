"""Skill executor — single source of truth shared by MCP and Telegram.

Each skill is a markdown file whose body is fed verbatim to the LLM as the
system prompt. The user's natural-language input becomes the user message.
One round-trip; structured output via the model's instinct from the
system prompt. No multi-step orchestration here — that's Phase 2 for the
2 fundraising hybrids (`research-vc` / `prep-week`).

The OpenRouter client is the BYOK-aware factory from `dormy.llm.client`,
so HTTP-mode MCP requests with `Authorization: Bearer <user_key>` get
billed to the user; CLI / stdio / Telegram-server fall back to the
shared `DORMY_OPENROUTER_API_KEY`.

Default model is Haiku 4.5 — fast, cheap (~$0.001/skill call), good
enough for prompt-following on framework-rich skill markdowns. Caller
can override via `model=` param for skills that benefit from Sonnet
(e.g. complex critique).
"""

from __future__ import annotations

from loguru import logger
from pydantic import BaseModel, Field

from dormy.llm.client import get_openrouter_client
from dormy.skills.registry import registry

DEFAULT_SKILL_MODEL = "anthropic/claude-haiku-4-5"
DEFAULT_MAX_TOKENS = 4096
DEFAULT_TEMPERATURE = 0.4  # slight bias to creativity for copy/strategy work


class SkillResult(BaseModel):
    name: str
    content: str = Field(description="Markdown body returned by the LLM")
    model: str
    tokens_used: int = Field(description="Total tokens (prompt + completion)")
    category: str
    data_source: str = Field(default="skill", description="skill | error")
    note: str = ""


def _error_result(name: str, category: str, message: str) -> SkillResult:
    return SkillResult(
        name=name,
        content="",
        model="",
        tokens_used=0,
        category=category,
        data_source="error",
        note=message,
    )


async def run_skill(
    name: str,
    input: str,
    model: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> SkillResult:
    """Execute a single skill: load its markdown as system prompt, one LLM call.

    Returns a SkillResult with `data_source="error"` on any failure rather
    than raising — callers (MCP / Telegram) need a structured payload back
    so the calling LLM can apologize / retry / fall back gracefully.
    """
    try:
        skill = registry.get(name)
    except KeyError as e:
        return _error_result(
            name=name,
            category="unknown",
            message=str(e),
        )

    chosen_model = model or DEFAULT_SKILL_MODEL
    try:
        client = get_openrouter_client()
    except RuntimeError as e:
        return _error_result(
            name=name,
            category=skill.category,
            message=f"LLM client unavailable: {e}",
        )

    try:
        resp = await client.chat.completions.create(
            model=chosen_model,
            messages=[
                {"role": "system", "content": skill.markdown},
                {"role": "user", "content": input},
            ],
            max_tokens=max_tokens,
            temperature=DEFAULT_TEMPERATURE,
        )
    except Exception as e:
        logger.warning(f"run_skill {name} failed: {e}")
        return _error_result(
            name=name,
            category=skill.category,
            message=f"skill call failed: {e}",
        )

    msg = resp.choices[0].message
    content = (msg.content or "").strip()
    usage = getattr(resp, "usage", None)
    tokens = getattr(usage, "total_tokens", 0) if usage else 0

    return SkillResult(
        name=name,
        content=content,
        model=chosen_model,
        tokens_used=int(tokens or 0),
        category=skill.category,
        data_source="skill",
        note=f"skill={name} model={chosen_model} tokens={tokens}",
    )
