"""user_observations CRUD + retrieval.

Async asyncpg interface. App-level user_id filtering (matches knowledge_chunks
pattern in 002_pgvector.sql; no Postgres RLS). Read by engine modules pre-prompt;
written by extractor.py post-conversation.

Schema: see migrations/005_user_observations.sql
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from dormy.db import get_pool

ObservationKind = Literal["preference", "fact", "goal", "concern", "pattern"]
ObservationSource = Literal["telegram", "cli", "mcp"]


@dataclass
class Observation:
    id: int
    user_id: UUID
    kind: ObservationKind
    tags: list[str]
    content: str
    confidence: float
    source: ObservationSource
    observed_at: datetime
    batch_id: UUID | None
    superseded_by: int | None


@dataclass
class NewObservation:
    """Fields that the extractor produces for a single observation."""

    kind: ObservationKind
    tags: list[str]
    content: str
    confidence: float
    source_message_ids: list[str]
    embedding: list[float] | None = None


async def insert_batch(
    user_id: UUID,
    source: ObservationSource,
    session_id: str | None,
    batch_id: UUID,
    observations: list[NewObservation],
    extracted_by_model: str = "claude-sonnet-4-6",
) -> int:
    """Insert a batch of observations from one extractor run.

    All observations in a batch share `batch_id` so we can audit / rollback /
    diff a single extraction run.

    Returns count of rows inserted.
    """
    raise NotImplementedError(
        "Step 2 follow-up: implement asyncpg INSERT with vector embedding "
        "via $N::vector parameter binding"
    )


async def retrieve_for_prompt(
    user_id: UUID,
    query_embedding: list[float] | None = None,
    recent_k: int = 10,
    similar_k: int = 5,
    kinds: list[ObservationKind] | None = None,
) -> list[Observation]:
    """Pull observations relevant to current conversation context.

    Strategy:
    - Pull `recent_k` most recent (by observed_at desc), optionally filtered by `kinds`
    - If `query_embedding` is provided, also pull `similar_k` top by cosine similarity
    - Filter out rows where `superseded_by IS NOT NULL`
    - Dedupe by id, sort by (confidence * recency_decay)

    Used by engine modules (find_investors / draft_intro / etc.) to inject
    founder context into LLM prompts without leaking other founders' data.

    The recency × confidence ranking is intentionally simple — Step 2 can iterate
    based on what produces useful prompts in practice.
    """
    raise NotImplementedError(
        "Step 2 follow-up: implement asyncpg SELECT with cosine similarity "
        "(<=> operator) plus recency union"
    )


async def supersede(observation_id: int, by_observation_id: int) -> None:
    """Mark an older observation as replaced by a newer one.

    Caller (typically the extractor's deduplication step) is responsible for
    detecting overlap. Set `superseded_by` instead of deleting so we preserve
    audit trail.
    """
    raise NotImplementedError("Step 2 follow-up: implement asyncpg UPDATE")


async def count_recent_messages_since_last_batch(
    user_id: UUID,
    source: ObservationSource,
    session_id: str | None,
) -> int:
    """How many user messages have come in since the last extractor batch ran.

    Used by the fire-and-forget hook on skill / MCP tool handlers to decide
    whether to trigger a new batch (≥ 10 messages → trigger).
    """
    raise NotImplementedError(
        "Step 2 follow-up: track per-session message counters; for v0.1 a "
        "simple SELECT max(observed_at) WHERE user_id = $1 might be sufficient"
    )


async def health() -> dict[str, object]:
    """Diagnostic — count observations, distinct users, latest batch."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval("select count(*) from user_observations")
        users = await conn.fetchval(
            "select count(distinct user_id) from user_observations"
        )
        latest = await conn.fetchval(
            "select max(observed_at) from user_observations"
        )
    return {
        "total_observations": int(total or 0),
        "distinct_users": int(users or 0),
        "latest_observed_at": str(latest) if latest else None,
    }
