"""deep_research — multi-step research via MiroThinker (api.miromind.ai).

OpenAI-compatible chat-completions API. The single available model
('mirothinker-1-7-30b-deepresearch') is an autonomous research agent
that can browse, summarize, cross-reference, and synthesize across
many sources before answering.

When to call: questions that need multi-step reasoning over external
sources — sector mapping, competitive analysis, "what's the consensus
on X", "find me 10 examples of Y". Not for one-shot fact lookup
(use web_search) or DB queries (use recent_funding / find_investors).

Cost note: Deep research is heavyweight. Each call is ~30-90s and
costs more than a single Sonnet call. The shared
DORMY_MIROTHINKER_API_KEY is server-paid; we'll add per-user
rate limits in v0.2 if abuse becomes a problem.

Apodex (currently the brand on platform.apodex.ai) is renaming to
MiroThinker; docs and API host are stable through the rename.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
from loguru import logger
from openai import APIError, AsyncOpenAI
from pydantic import BaseModel, Field

from dormy.config import settings
from dormy.memory.hooks import from_mcp_call

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


MIROTHINKER_BASE_URL = "https://api.miromind.ai/v1"
DEFAULT_MODEL = "mirothinker-1-7-30b-deepresearch"
# Deep research can take 30-90s. Be patient but bound it.
HTTP_TIMEOUT_SECONDS = 180.0


class DeepResearchResult(BaseModel):
    question: str
    answer: str
    model: str
    data_source: str = Field(description="mirothinker | error")
    note: str
    duration_seconds: float | None = None


def _error_result(question: str, message: str) -> DeepResearchResult:
    return DeepResearchResult(
        question=question,
        answer="",
        model=DEFAULT_MODEL,
        data_source="error",
        note=message,
        duration_seconds=None,
    )


def register(mcp: "FastMCP") -> None:
    @mcp.tool(
        description=(
            "Run deep, multi-step research via MiroThinker's autonomous "
            "research agent. Use ONLY for questions that need cross-referencing "
            "across many sources or extended reasoning ('map the AI infra "
            "fundraising landscape last quarter', 'summarize consensus on "
            "X among Y'). For single-fact lookup, use web_search instead. "
            "For curated funding data, use recent_funding. Each call is "
            "expensive (~30-90s, server-paid)."
        ),
    )
    async def deep_research(
        question: str = Field(
            description="A specific, multi-step research question",
            min_length=10,
        ),
        context: str | None = Field(
            default=None,
            description="Optional founder/sector context to focus the research",
        ),
        model: str = Field(
            default=DEFAULT_MODEL,
            description="MiroThinker model id; default is the deep-research variant",
        ),
    ) -> DeepResearchResult:
        api_key = settings.mirothinker_api_key
        if not api_key:
            result = _error_result(
                question,
                "DORMY_MIROTHINKER_API_KEY not configured on server. "
                "Tell the user deep research is not available right now.",
            )
            from_mcp_call(
                "deep_research",
                {"question": question, "context": context, "model": model},
                result,
            )
            return result

        messages: list[dict[str, str]] = []
        if context:
            messages.append({"role": "system", "content": context})
        messages.append({"role": "user", "content": question})

        client = AsyncOpenAI(
            api_key=api_key,
            base_url=MIROTHINKER_BASE_URL,
            timeout=httpx.Timeout(HTTP_TIMEOUT_SECONDS),
            max_retries=0,
        )

        import time
        started = time.monotonic()
        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=messages,
                stream=False,
            )
        except APIError as e:
            logger.warning(f"mirothinker API error: {e}")
            result = _error_result(question, f"MiroThinker API error: {e}")
        except httpx.TimeoutException:
            logger.warning("mirothinker timed out")
            result = _error_result(
                question,
                f"MiroThinker timed out after {HTTP_TIMEOUT_SECONDS}s. "
                "Try a more focused question or split into sub-questions.",
            )
        except Exception as e:
            logger.warning(f"mirothinker request failed: {e}")
            result = _error_result(question, f"deep research failed: {e}")
        else:
            duration = time.monotonic() - started
            answer = ""
            if resp.choices:
                msg = resp.choices[0].message
                answer = (msg.content or "") if msg else ""
            result = DeepResearchResult(
                question=question,
                answer=answer,
                model=model,
                data_source="mirothinker",
                note=f"MiroThinker deep research returned {len(answer)} chars in {duration:.1f}s.",
                duration_seconds=round(duration, 2),
            )

        from_mcp_call(
            "deep_research",
            {"question": question, "context": context, "model": model},
            result,
        )
        return result
