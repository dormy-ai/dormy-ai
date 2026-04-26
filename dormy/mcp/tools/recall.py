"""memory_recall — RAG retrieval from Dormy's knowledge base.

Week 3: connected to Supabase `knowledge_chunks` via `dormy.knowledge.retrieve`.
If DB is empty or unreachable, falls back to in-process mock constants so the
tool always returns SOMETHING (with a clear `data_source` note).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger
from pydantic import BaseModel, Field

from dormy.knowledge.retrieve import recall as knowledge_recall
from dormy.mcp.mocks import KNOWLEDGE_CHUNKS
from dormy.memory.hooks import from_mcp_call

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


class KnowledgeChunkOut(BaseModel):
    source: str
    source_path: str | None = None
    title: str | None = None
    excerpt: str
    score: float = Field(ge=0, le=1)
    tags: list[str] = []


class RecallResult(BaseModel):
    query: str
    chunks: list[KnowledgeChunkOut]
    count: int
    data_source: str = Field(
        description="semantic | lexical | empty | mock | no_database"
    )
    note: str


def _build_from_mock(query: str, tags: list[str] | None, n: int) -> RecallResult:
    candidates = KNOWLEDGE_CHUNKS
    if tags:
        want = {t.lower() for t in tags}
        candidates = [
            c for c in candidates if want & {t.lower() for t in c.get("tags", [])}
        ]
    picked = sorted(candidates, key=lambda c: c["score"], reverse=True)[:n]
    return RecallResult(
        query=query,
        chunks=[KnowledgeChunkOut(**c, source_path=None) for c in picked],
        count=len(picked),
        data_source="mock",
        note="⚠️ DB empty or unreachable — falling back to 3 hardcoded mock chunks.",
    )


def register(mcp: "FastMCP") -> None:
    @mcp.tool(
        description=(
            "Retrieve relevant chunks from Dormy's knowledge base "
            "(curated Newsletter corpus + Obsidian Dormy/ folder). "
            "Uses semantic pgvector search when embeddings are present; "
            "falls back to lexical ILIKE search otherwise, then to mock."
        ),
    )
    async def memory_recall(
        query: str = Field(description="Natural-language query"),
        tags: list[str] | None = Field(
            default=None,
            description="Filter by tags, e.g. ['gtm', 'positioning']",
        ),
        n: int = Field(default=5, ge=1, le=20),
    ) -> RecallResult:
        try:
            hits, mode = await knowledge_recall(query=query, tags=tags, limit=n)
        except Exception as e:
            logger.warning(f"retrieve failed, fallback to mock: {e}")
            result = _build_from_mock(query, tags, n)
        else:
            if not hits:
                result = _build_from_mock(query, tags, n)
            else:
                result = RecallResult(
                    query=query,
                    chunks=[
                        KnowledgeChunkOut(
                            source=h.source,
                            source_path=h.source_path,
                            title=h.title,
                            excerpt=h.excerpt,
                            score=h.score,
                            tags=h.tags,
                        )
                        for h in hits
                    ],
                    count=len(hits),
                    data_source=mode,
                    note=(
                        "semantic: OpenAI embeddings + pgvector cosine sim"
                        if mode == "semantic"
                        else "lexical: ILIKE fallback (add DORMY_OPENAI_API_KEY for semantic RAG)"
                    ),
                )

        from_mcp_call(
            "memory_recall",
            {"query": query, "tags": tags, "n": n},
            result,
        )
        return result
