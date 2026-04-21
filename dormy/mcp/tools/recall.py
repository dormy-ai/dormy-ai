"""dormy_memory_recall — RAG retrieval from Dormy's knowledge base (mock)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from dormy.mcp.mocks import KNOWLEDGE_CHUNKS

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


class KnowledgeChunk(BaseModel):
    source: str
    title: str
    excerpt: str
    score: float = Field(ge=0, le=1)
    tags: list[str]


class RecallResult(BaseModel):
    query: str
    chunks: list[KnowledgeChunk]
    count: int
    note: str


def register(mcp: "FastMCP") -> None:
    @mcp.tool(
        description=(
            "Retrieve relevant chunks from Dormy's knowledge base (curated Newsletter corpus + "
            "Obsidian Dormy/ folder). Useful for fundraising/GTM playbook queries like "
            "'pitch deck tips' or 'PLG → enterprise upsell'. "
            "[Week 2 Step 1: returns mock chunks — Supabase pgvector + time-weighted scoring lands Week 3.]"
        ),
    )
    def dormy_memory_recall(
        query: str = Field(description="Natural-language query"),
        tags: list[str] | None = Field(
            default=None,
            description="Filter by tags, e.g. ['gtm', 'positioning']",
        ),
        n: int = Field(default=5, ge=1, le=20),
    ) -> RecallResult:
        candidates = KNOWLEDGE_CHUNKS
        if tags:
            want = {t.lower() for t in tags}
            candidates = [
                c for c in candidates
                if want & {t.lower() for t in c.get("tags", [])}
            ]

        # Mock "relevance ranking": just take top N by pre-baked score
        picked = sorted(candidates, key=lambda c: c["score"], reverse=True)[:n]
        chunks = [KnowledgeChunk(**c) for c in picked]

        return RecallResult(
            query=query,
            chunks=chunks,
            count=len(chunks),
            note=(
                f"⚠️ MOCK — 3 handpicked chunks regardless of query. "
                f"Real pgvector RAG (text-embedding-3-small + time-decay scoring) lands Week 3."
            ),
        )
