"""Run SQL migrations in order against DORMY_DATABASE_URL.

Usage:
    uv run python scripts/run_migrations.py

Reads .env (via dormy.config), then applies every `migrations/NNN_*.sql`
in ascending filename order. Idempotent — each migration uses
`CREATE TABLE IF NOT EXISTS` / `CREATE EXTENSION IF NOT EXISTS`.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import asyncpg
from dotenv import load_dotenv
from loguru import logger


MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"
load_dotenv(Path(__file__).parent.parent / ".env")


async def run_migration(conn: asyncpg.Connection, path: Path) -> None:
    """Execute a single .sql file."""
    sql = path.read_text()
    logger.info(f"Applying {path.name} ({len(sql):,} bytes)")
    # asyncpg supports multi-statement SQL via execute()
    await conn.execute(sql)
    logger.success(f"✓ {path.name}")


async def list_tables(conn: asyncpg.Connection) -> list[str]:
    rows = await conn.fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
    )
    return [r["tablename"] for r in rows]


async def main() -> None:
    url = os.environ.get("DORMY_DATABASE_URL")
    if not url:
        logger.error("DORMY_DATABASE_URL not set in environment or .env")
        sys.exit(1)

    # Mask the password for logging
    logger.info(f"Connecting to {url.split('@')[-1]}")

    # statement_cache_size=0 disables prepared statements
    # (required for PgBouncer-based Supabase Session Pooler)
    conn = await asyncpg.connect(url, statement_cache_size=0)
    try:
        sql_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
        if not sql_files:
            logger.warning(f"No migrations found in {MIGRATIONS_DIR}")
            return

        logger.info(f"Found {len(sql_files)} migration file(s)")
        for path in sql_files:
            await run_migration(conn, path)

        tables = await list_tables(conn)
        logger.success(f"Done. Tables now in public schema ({len(tables)}):")
        for t in tables:
            logger.info(f"  - {t}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
