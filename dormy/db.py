"""Database layer — Supabase Postgres via asyncpg.

Uses PgBouncer Session Pooler: `statement_cache_size=0` disables prepared
statements (required for pooler compatibility).

Lazy-initialized single pool per process. Call `close_pool()` on shutdown.
"""

from __future__ import annotations

import asyncpg
from loguru import logger

from dormy.config import settings


_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    """Lazy-init a connection pool. One pool per process."""
    global _pool
    if _pool is None:
        if not settings.database_url:
            raise RuntimeError(
                "DORMY_DATABASE_URL not configured — set it in .env or environment"
            )
        logger.debug(f"Creating asyncpg pool to {settings.database_url.split('@')[-1]}")
        _pool = await asyncpg.create_pool(
            settings.database_url,
            min_size=1,
            max_size=5,
            statement_cache_size=0,  # PgBouncer Session Pooler compat
        )
    return _pool


async def close_pool() -> None:
    """Close the pool (call at shutdown)."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def ping() -> dict[str, object]:
    """Health check. Returns diagnostic info about connection + schema."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        one = await conn.fetchval("SELECT 1")
        tables = await conn.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
        )
        version = await conn.fetchval("SELECT version()")
    return {
        "ok": one == 1,
        "postgres_version": str(version).split(",")[0] if version else None,
        "table_count": len(tables),
        "tables": [r["tablename"] for r in tables],
    }
