"""Sonnet 4.6 batch observation extractor.

Pipeline:
1. Triggered after every 10 user messages OR daily 03:00 cron (whichever first)
2. Pulls recent unprocessed messages from session / conversation log (caller's job)
3. Calls Sonnet 4.6 via OpenRouter with the extraction prompt
4. Parses output into 5-typed observations (preference/fact/goal/concern/pattern)
5. Embeds each observation's content via text-embedding-3-small (1536 dim)
6. Inserts batch via observations.insert_batch with shared batch_id

Cost: ~5k tokens input + 1k output per batch on Sonnet 4.6 ≈ $0.03/batch.
At 1–2 batches/day/user, ~$1.5/user/month. Within Stripe 5% markup envelope.

Design: see DESIGN.md "Long-term memory design" + plan file
~/.claude/plans/repo-https-franklin-run-https-github-co-rippling-moore.md
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from uuid import UUID, uuid4

from loguru import logger

from dormy.config import settings
from dormy.knowledge.embedder import embed_batch
from dormy.memory.observations import (
    NewObservation,
    ObservationSource,
    insert_batch,
)

EXTRACTION_MODEL = "anthropic/claude-sonnet-4-6"
EXTRACTION_MAX_TOKENS = 2048
EXTRACTION_TEMPERATURE = 0.1
MAX_OBSERVATIONS_PER_BATCH = 8
MAX_CONTENT_CHARS = 240
MAX_TAGS = 5
VALID_KINDS = {"preference", "fact", "goal", "concern", "pattern"}


@dataclass
class ConversationMessage:
    """One turn in the conversation under analysis."""

    id: str  # opaque id (nanobot session jsonl line index, telegram message id, etc.)
    role: str  # "user" | "assistant" | "tool"
    content: str
    timestamp: str | None = None  # ISO


@dataclass
class ExtractionInput:
    user_id: UUID
    source: ObservationSource
    session_id: str | None
    messages: list[ConversationMessage]
    prior_observations_summary: str = ""  # recent observations to dedupe against


@dataclass
class ExtractionOutput:
    batch_id: UUID
    new_observations: list[NewObservation]
    superseded_observation_ids: list[int] = field(default_factory=list)
    raw_llm_output: str = ""  # for debugging / re-parsing
    error: str | None = None


def build_extraction_prompt(input: ExtractionInput) -> str:
    """Build the Sonnet 4.6 prompt for one extraction batch.

    Output contract: a JSON array, each element with keys
    {kind, tags, content, confidence, source_message_ids}.

    Voice rules from PRODUCT.md / DESIGN.md:
    - Direct. Useful. Dry. No hedging.
    - Mirror founder's language (English / Chinese).
    - Strip filler ("the user maybe wants" → "wants X").
    """
    transcript = "\n".join(
        f"[{m.role}] (id: {m.id}) {m.content}" for m in input.messages
    )
    prior_section = (
        f"\n\nPrior observations about this founder (avoid duplicating):\n"
        f"{input.prior_observations_summary}"
        if input.prior_observations_summary
        else ""
    )
    return (
        "You are extracting durable observations about a founder from their "
        "recent conversation with the Dormy fundraising copilot.\n\n"
        "Output ONLY a JSON array. Each element MUST have exactly these keys:\n"
        '- "kind": one of "preference", "fact", "goal", "concern", "pattern"\n'
        '- "tags": array of 1-5 lowercase kebab-case strings (e.g. '
        '["fundraising", "seed-stage", "eu-market"])\n'
        f'- "content": single sentence ≤ {MAX_CONTENT_CHARS} chars stating the observation\n'
        '- "confidence": float 0.0-1.0 (your certainty)\n'
        '- "source_message_ids": array of message ids from the conversation '
        "that support this observation\n\n"
        "Rules:\n"
        "- Only extract observations directly supported by the conversation.\n"
        '- Skip ephemeral comments ("I\'m tired today", "let me think").\n'
        '- Direct, useful, dry voice. No hedging ("seems to", "may be").\n'
        "- Mirror the founder's language (English or Chinese).\n"
        "- If nothing durable to extract, output: []\n"
        f"- Maximum {MAX_OBSERVATIONS_PER_BATCH} observations per batch.\n\n"
        f"Recent conversation:\n{transcript}{prior_section}\n\n"
        "JSON array only, no commentary:"
    )


def _parse_observations(raw: str) -> list[NewObservation]:
    """Parse Sonnet's text output into NewObservation objects.

    Robust: strips optional code fences, extracts first JSON array, tolerates
    surrounding commentary, drops malformed entries with a warning log.
    """
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        logger.warning(
            f"extractor: no JSON array in LLM output: {raw[:200]!r}"
        )
        return []
    try:
        items = json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(
            f"extractor: JSON parse failed: {e} — output: {raw[:200]!r}"
        )
        return []

    out: list[NewObservation] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        if kind not in VALID_KINDS:
            continue
        content = item.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        try:
            confidence = float(item.get("confidence", 0.7))
            confidence = max(0.0, min(1.0, confidence))
        except (TypeError, ValueError):
            confidence = 0.7
        tags_in = item.get("tags") or []
        tags = [t.lower() for t in tags_in if isinstance(t, str)][:MAX_TAGS]
        msgs_in = item.get("source_message_ids") or []
        source_message_ids = [m for m in msgs_in if isinstance(m, str)]
        out.append(
            NewObservation(
                kind=kind,
                tags=tags,
                content=content.strip()[:MAX_CONTENT_CHARS],
                confidence=confidence,
                source_message_ids=source_message_ids,
            )
        )
        if len(out) >= MAX_OBSERVATIONS_PER_BATCH:
            break
    return out


async def _call_sonnet(prompt: str) -> str:
    """Call Sonnet 4.6 via OpenRouter, return raw text response."""
    if not settings.openrouter_api_key:
        raise RuntimeError(
            "DORMY_OPENROUTER_API_KEY not set — required for extractor LLM calls"
        )
    # Lazy import so observations.py can be imported without openai installed paths
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        api_key=settings.openrouter_api_key,
        base_url="https://openrouter.ai/api/v1",
    )
    resp = await client.chat.completions.create(
        model=EXTRACTION_MODEL,
        max_tokens=EXTRACTION_MAX_TOKENS,
        temperature=EXTRACTION_TEMPERATURE,
        messages=[{"role": "user", "content": prompt}],
    )
    return (resp.choices[0].message.content or "").strip()


async def extract_and_embed_concurrent(
    contents: list[str],
) -> list[list[float] | None]:
    """Embed N observation contents via OpenAI text-embedding-3-small.

    Delegates to dormy.knowledge.embedder.embed_batch (which already handles
    batching + graceful NULL fallback when no OpenAI key is set).

    text-embedding-3-small returns 1536-dim vectors that match the
    user_observations.embedding column dimension.
    """
    if not contents:
        return []
    return await embed_batch(contents)


async def run_batch(input: ExtractionInput) -> ExtractionOutput:
    """Run one extraction batch end-to-end.

    Steps:
    1. Build prompt
    2. Call Sonnet 4.6 via OpenRouter
    3. Parse JSON output into NewObservation list
    4. Embed each content via text-embedding-3-small (in parallel)
    5. observations.insert_batch with shared batch_id

    Fire-and-forget callable from skill / MCP tool handlers via
    `asyncio.create_task(run_batch(...))` — caller does NOT await.

    Errors are logged via loguru but never raised — extractor failure must
    NEVER break the user-facing skill response.
    """
    batch_id = uuid4()
    if not input.messages:
        return ExtractionOutput(batch_id=batch_id, new_observations=[])

    prompt = build_extraction_prompt(input)
    raw_text = ""
    try:
        raw_text = await _call_sonnet(prompt)
    except Exception as e:
        logger.error(f"extractor: Sonnet call failed: {e}")
        return ExtractionOutput(
            batch_id=batch_id,
            new_observations=[],
            raw_llm_output="",
            error=str(e),
        )

    observations = _parse_observations(raw_text)
    if not observations:
        logger.info(
            f"extractor: 0 observations parsed for user={input.user_id} "
            f"batch={batch_id}"
        )
        return ExtractionOutput(
            batch_id=batch_id,
            new_observations=[],
            raw_llm_output=raw_text,
        )

    try:
        embeddings = await extract_and_embed_concurrent(
            [obs.content for obs in observations]
        )
        for obs, emb in zip(observations, embeddings, strict=True):
            obs.embedding = emb
    except Exception as e:
        logger.warning(f"extractor: embedding failed, inserting NULLs: {e}")
        # observations keep embedding=None — still useful for kind/tag retrieval

    try:
        await insert_batch(
            user_id=input.user_id,
            source=input.source,
            session_id=input.session_id,
            batch_id=batch_id,
            observations=observations,
            extracted_by_model=EXTRACTION_MODEL,
        )
    except Exception as e:
        logger.error(f"extractor: insert_batch failed: {e}")
        return ExtractionOutput(
            batch_id=batch_id,
            new_observations=observations,
            raw_llm_output=raw_text,
            error=str(e),
        )

    logger.info(
        f"extractor: user={input.user_id} batch={batch_id} "
        f"inserted {len(observations)} observations"
    )
    return ExtractionOutput(
        batch_id=batch_id,
        new_observations=observations,
        raw_llm_output=raw_text,
    )
