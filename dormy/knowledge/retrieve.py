"""Knowledge retrieval — pgvector cosine similarity with ILIKE fallback.

Retrieval modes:
- SEMANTIC  — used when OpenAI key is set AND query can be embedded
- LEXICAL   — ILIKE fallback when no key (or embedding fails). Splits the
              query into terms, matches any term in content or title.

Both modes return the same shape so callers (MCP `memory_recall`) can
transparently use whichever is available.
"""

from __future__ import annotations

from dataclasses import dataclass

import asyncpg
from loguru import logger

from dormy.config import settings
from dormy.knowledge.embedder import embed_batch, have_embeddings


@dataclass(slots=True)
class ChunkHit:
    source: str
    source_path: str | None
    title: str | None
    excerpt: str
    score: float
    tags: list[str]
    retrieval_mode: str


def _excerpt(text: str, max_chars: int = 280) -> str:
    text = text.replace("\n", " ").strip()
    return text if len(text) <= max_chars else text[: max_chars - 1] + "…"


async def _semantic_query(
    conn: asyncpg.Connection,
    *,
    query: str,
    tags: list[str] | None,
    user_id: str | None,
    limit: int,
) -> list[ChunkHit]:
    """pgvector cosine similarity search. Requires an embedding vector."""
    vecs = await embed_batch([query])
    vec = vecs[0] if vecs else None
    if vec is None:
        return []
    vec_literal = "[" + ",".join(f"{x:.6f}" for x in vec) + "]"

    sql = """
        SELECT source, source_path, title, content, tags,
               1 - (embedding <=> $1::vector) AS score
          FROM knowledge_chunks
         WHERE embedding IS NOT NULL
           AND ($2::uuid IS NULL OR user_id = $2 OR user_id IS NULL)
           AND ($3::text[] IS NULL OR tags && $3)
         ORDER BY embedding <=> $1::vector
         LIMIT $4
    """
    rows = await conn.fetch(sql, vec_literal, user_id, tags, limit)
    return [
        ChunkHit(
            source=r["source"],
            source_path=r["source_path"],
            title=r["title"],
            excerpt=_excerpt(r["content"]),
            score=float(r["score"]),
            tags=list(r["tags"] or []),
            retrieval_mode="semantic",
        )
        for r in rows
    ]


async def _lexical_query(
    conn: asyncpg.Connection,
    *,
    query: str,
    tags: list[str] | None,
    user_id: str | None,
    limit: int,
) -> list[ChunkHit]:
    """ILIKE full-text fallback. Treats space-separated words as ORed terms."""
    terms = [t.strip() for t in query.split() if len(t.strip()) >= 2]
    if not terms:
        return []
    like_patterns = [f"%{t}%" for t in terms]

    # Score = count of matching terms in content OR title.
    # Putting unnest in FROM so `p.pat` is a real column in WHERE scope.
    sql = """
        WITH candidates AS (
            SELECT kc.source, kc.source_path, kc.title, kc.content, kc.tags,
                   (
                       SELECT count(*)
                         FROM unnest($1::text[]) AS p(pat)
                        WHERE kc.content ILIKE p.pat
                           OR coalesce(kc.title,'') ILIKE p.pat
                   ) AS hits
              FROM knowledge_chunks kc
             WHERE ($2::uuid IS NULL OR kc.user_id = $2 OR kc.user_id IS NULL)
               AND ($3::text[] IS NULL OR kc.tags && $3)
        )
        SELECT source, source_path, title, content, tags,
               hits::float / $4::float AS score
          FROM candidates
         WHERE hits > 0
         ORDER BY hits DESC, length(content) ASC
         LIMIT $5
    """
    rows = await conn.fetch(
        sql, like_patterns, user_id, tags, len(terms), limit
    )
    return [
        ChunkHit(
            source=r["source"],
            source_path=r["source_path"],
            title=r["title"],
            excerpt=_excerpt(r["content"]),
            score=float(r["score"]),
            tags=list(r["tags"] or []),
            retrieval_mode="lexical",
        )
        for r in rows
    ]


async def recall(
    *,
    query: str,
    tags: list[str] | None = None,
    user_id: str | None = None,
    limit: int = 5,
) -> tuple[list[ChunkHit], str]:
    """Top entry point. Returns (hits, retrieval_mode).

    retrieval_mode is 'semantic' if vector search returned anything,
    else 'lexical' if ILIKE returned anything, else 'empty'.
    """
    if not settings.database_url:
        return [], "no_database"

    conn = await asyncpg.connect(settings.database_url, statement_cache_size=0)
    try:
        if have_embeddings():
            hits = await _semantic_query(
                conn, query=query, tags=tags, user_id=user_id, limit=limit
            )
            if hits:
                return hits, "semantic"
            logger.debug("semantic query empty; trying lexical fallback")

        hits = await _lexical_query(
            conn, query=query, tags=tags, user_id=user_id, limit=limit
        )
        return hits, ("lexical" if hits else "empty")
    finally:
        await conn.close()
