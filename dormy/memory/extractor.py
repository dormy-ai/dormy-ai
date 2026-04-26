"""Sonnet 4.6 batch observation extractor.

Pipeline:
1. Triggered after every 10 user messages OR daily 03:00 cron (whichever first)
2. Pulls recent unprocessed messages from session / conversation log
3. Calls Sonnet 4.6 with the extraction prompt (see build_extraction_prompt)
4. Parses output into 5-typed observations (preference/fact/goal/concern/pattern)
5. Embeds each observation's content via text-embedding-3-small (1536 dim)
6. Inserts batch via observations.insert_batch with shared batch_id
7. Optionally deduplicates / supersedes overlapping prior observations

Design: see DESIGN.md "Extractor pipeline" + plan file at
~/.claude/plans/repo-https-franklin-run-https-github-co-rippling-moore.md
"Long-term memory design" section.

Cost: ~5k tokens input + 1k output per batch on Sonnet 4.6 ≈ $0.03/batch.
At 1–2 batches/day/user, ~$1.5/user/month. Well within Stripe 5% markup envelope.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid4

from dormy.memory.observations import (
    NewObservation,
    ObservationSource,
)


@dataclass
class ConversationMessage:
    """One turn in the conversation under analysis."""

    id: str  # opaque id (e.g. nanobot session jsonl line index, telegram message id)
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


async def run_batch(input: ExtractionInput) -> ExtractionOutput:
    """Run one extraction batch end-to-end.

    Steps:
    1. Build prompt with build_extraction_prompt
    2. Call Sonnet 4.6 via OpenRouter (settings.openrouter_api_key)
    3. Parse JSON output → list[NewObservation]
    4. Embed each `content` via OpenRouter text-embedding-3-small (batched)
    5. observations.insert_batch with shared batch_id
    6. (optional) detect supersedes — for v0.1 leave as no-op

    Fire-and-forget callable from skill / MCP tool handlers via
    `asyncio.create_task(run_batch(...))` — caller does NOT await.

    Errors are logged via loguru, not raised — extractor failure must NOT
    break the user-facing skill response.
    """
    raise NotImplementedError(
        "Step 2 follow-up: implement Sonnet 4.6 LLM call via OpenRouter, "
        "parse strict JSON output, embed via text-embedding-3-small, "
        "call observations.insert_batch"
    )


def build_extraction_prompt(input: ExtractionInput) -> str:
    """Build the Sonnet 4.6 prompt for one extraction batch.

    Returns a prompt that instructs Sonnet to output strictly JSON in this shape:

    [
      {
        "kind": "fact",
        "tags": ["fundraising", "seed"],
        "content": "Founder is raising a $2M seed round, in talks with Sequoia and a16z",
        "confidence": 0.85,
        "source_message_ids": ["msg_abc", "msg_def"]
      },
      ...
    ]

    Schema constraints (validated post-parse, malformed observations dropped):
    - kind ∈ {preference, fact, goal, concern, pattern}
    - tags: ≤ 5 free-form strings, lowercased, kebab-case
    - content: ≤ 240 chars, single sentence preferred
    - confidence: float in [0, 1]
    - source_message_ids: list of ids from the input messages

    Voice rules (from PRODUCT.md / DESIGN.md):
    - Direct. Useful. Dry. No hedging.
    - English by default, mirror founder's language if Chinese
    - Strip filler: "I think the user maybe wants..." → "Wants X"
    """
    raise NotImplementedError(
        "Step 2 follow-up: design and iterate the extraction prompt. "
        "Test cases: pure-fact founder profile updates, ambiguous goals, "
        "Chinese-English code-switching, contradictions with prior observations."
    )


async def extract_and_embed_concurrent(
    contents: list[str],
) -> list[list[float]]:
    """Embed N observation contents in parallel via OpenRouter.

    text-embedding-3-small returns 1536-dim vectors that match the
    knowledge_chunks embedding column dimension.
    """
    raise NotImplementedError("Step 2 follow-up: parallel httpx calls to OpenRouter embeddings endpoint")
