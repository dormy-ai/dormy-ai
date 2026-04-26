"""Embedder — OpenAI text-embedding-3-small with graceful NULL fallback.

When DORMY_OPENAI_API_KEY is not set, `embed_batch()` returns `[None, ...]`
so the ingest pipeline can still populate knowledge_chunks with content
(retrievable via ILIKE full-text search). Adding the key later allows
a re-sync to backfill embeddings.

We explicitly pin `base_url=https://api.openai.com/v1` so the OpenAI SDK
never honors a stray `OPENAI_BASE_URL` env var (e.g. set to OpenRouter
elsewhere in the dev environment) — which would otherwise route OpenAI
embedding requests through a different host and 401 on key format mismatch.
"""

from __future__ import annotations

from loguru import logger

from dormy.config import settings

MODEL = "text-embedding-3-small"
DIMS = 1536
OPENAI_BASE_URL = "https://api.openai.com/v1"


def have_embeddings() -> bool:
    return bool(settings.openai_api_key)


async def embed_batch(texts: list[str]) -> list[list[float] | None]:
    """Embed many texts in one API call. Returns None entries if no key."""
    if not have_embeddings():
        return [None] * len(texts)

    # Import lazily so no-key path stays fast
    from openai import AsyncOpenAI

    # base_url pinned to OpenAI direct — defends against OPENAI_BASE_URL env
    # being set to a proxy / OpenRouter URL elsewhere in the environment.
    client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=OPENAI_BASE_URL,
    )
    # OpenAI embeddings endpoint supports up to 2048 inputs per call
    out: list[list[float] | None] = []
    batch_size = 100
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        try:
            resp = await client.embeddings.create(model=MODEL, input=batch)
            out.extend([d.embedding for d in resp.data])
        except Exception as e:
            logger.warning(f"embedding batch {i} failed ({e}); inserting NULLs")
            out.extend([None] * len(batch))
    return out
