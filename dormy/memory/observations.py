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

from loguru import logger

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
    """Fields the extractor produces for a single observation."""

    kind: ObservationKind
    tags: list[str]
    content: str
    confidence: float
    source_message_ids: list[str]
    embedding: list[float] | None = None


def _vec_literal(vec: list[float] | None) -> str | None:
    """Format embedding for asyncpg `$N::vector` parameter binding.

    Same shape as dormy.knowledge.retrieve._semantic_query.
    """
    if vec is None:
        return None
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"


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

    Returns count of rows inserted. Per-row execute (not executemany) for
    PgBouncer Session Pooler compatibility (statement_cache_size=0 already
    applied in dormy.db).
    """
    if not observations:
        return 0
    pool = await get_pool()
    inserted = 0
    async with pool.acquire() as conn:
        for obs in observations:
            await conn.execute(
                """
                INSERT INTO user_observations (
                    user_id, source, session_id,
                    kind, tags, content, confidence,
                    source_message_ids, batch_id, extracted_by_model,
                    embedding
                ) VALUES (
                    $1, $2, $3,
                    $4, $5, $6, $7,
                    $8, $9, $10,
                    $11::vector
                )
                """,
                user_id,
                source,
                session_id,
                obs.kind,
                list(obs.tags or []),
                obs.content,
                obs.confidence,
                list(obs.source_message_ids or []),
                batch_id,
                extracted_by_model,
                _vec_literal(obs.embedding),
            )
            inserted += 1
    logger.debug(
        f"observations.insert_batch: user={user_id} source={source} "
        f"batch={batch_id} count={inserted}"
    )
    return inserted


async def retrieve_for_prompt(
    user_id: UUID,
    query_embedding: list[float] | None = None,
    recent_k: int = 10,
    similar_k: int = 5,
    kinds: list[ObservationKind] | None = None,
) -> list[Observation]:
    """Pull observations relevant to current conversation context.

    Strategy:
    - Always pull `recent_k` most recent (by observed_at desc), filtered by `kinds`
    - If `query_embedding` is provided, also pull `similar_k` top by cosine similarity
    - Filter out rows where `superseded_by IS NOT NULL`
    - Dedupe by id, sort by (confidence, recency) desc

    Used by engine modules (find_investors / draft_intro / etc.) to inject
    founder context into LLM prompts without leaking other founders' data.
    """
    kinds_param = list(kinds) if kinds else None
    pool = await get_pool()
    rows_by_id: dict[int, dict] = {}

    async with pool.acquire() as conn:
        recent_rows = await conn.fetch(
            """
            SELECT id, user_id, observed_at, source, session_id, kind,
                   tags, content, confidence, batch_id, superseded_by
              FROM user_observations
             WHERE user_id = $1
               AND superseded_by IS NULL
               AND ($2::text[] IS NULL OR kind = ANY($2))
             ORDER BY observed_at DESC
             LIMIT $3
            """,
            user_id,
            kinds_param,
            recent_k,
        )
        for r in recent_rows:
            rows_by_id[r["id"]] = r

        if query_embedding is not None:
            similar_rows = await conn.fetch(
                """
                SELECT id, user_id, observed_at, source, session_id, kind,
                       tags, content, confidence, batch_id, superseded_by
                  FROM user_observations
                 WHERE user_id = $1
                   AND superseded_by IS NULL
                   AND embedding IS NOT NULL
                   AND ($2::text[] IS NULL OR kind = ANY($2))
                 ORDER BY embedding <=> $3::vector
                 LIMIT $4
                """,
                user_id,
                kinds_param,
                _vec_literal(query_embedding),
                similar_k,
            )
            for r in similar_rows:
                rows_by_id.setdefault(r["id"], r)

    out = [
        Observation(
            id=r["id"],
            user_id=r["user_id"],
            kind=r["kind"],
            tags=list(r["tags"] or []),
            content=r["content"],
            confidence=float(r["confidence"]),
            source=r["source"],
            observed_at=r["observed_at"],
            batch_id=r["batch_id"],
            superseded_by=r["superseded_by"],
        )
        for r in rows_by_id.values()
    ]
    out.sort(key=lambda o: (o.confidence, o.observed_at), reverse=True)
    return out


async def supersede(observation_id: int, by_observation_id: int) -> None:
    """Mark an older observation as replaced by a newer one.

    Caller (typically the extractor's deduplication step) is responsible for
    detecting overlap. We set `superseded_by` instead of deleting so we
    preserve the audit trail.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE user_observations SET superseded_by = $1 WHERE id = $2",
            by_observation_id,
            observation_id,
        )


async def latest_batch_time(
    user_id: UUID,
    source: ObservationSource,
    session_id: str | None = None,
) -> datetime | None:
    """When was the last extractor batch run for this user / source / session?

    Returns None if no batch has ever produced observations for this scope.

    The caller (skill handler / MCP tool) combines this with its own message
    counter to decide whether to trigger a new batch:
      - Time-based: `now() - latest_batch_time(...) > timedelta(hours=24)` → trigger
      - Message-based: caller tracks N messages since last trigger; ≥ 10 → trigger
      - Whichever fires first
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        if session_id is None:
            row = await conn.fetchval(
                """
                SELECT max(observed_at) FROM user_observations
                 WHERE user_id = $1 AND source = $2
                """,
                user_id,
                source,
            )
        else:
            row = await conn.fetchval(
                """
                SELECT max(observed_at) FROM user_observations
                 WHERE user_id = $1 AND source = $2 AND session_id = $3
                """,
                user_id,
                source,
                session_id,
            )
    return row


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
