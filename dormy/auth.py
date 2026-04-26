"""User identity layer.

Hash BYOK key → look up or lazy-create users row → return user_id UUID.

Used by:
  - BYOKMiddleware (HTTP requests carry Authorization: Bearer <key>)
  - get_current_user_id() helper (CLI / stdio fallback to settings.user_id)

We never persist the raw OpenRouter key; the column users.api_key stores
SHA256(key)[:32]. Synthetic email `byok-<hash[:12]>@dormy.local` prevents
collisions with real future signups (when an explicit auth UI lands).
"""

from __future__ import annotations

import hashlib
from uuid import UUID

from loguru import logger

from dormy.config import settings
from dormy.db import get_pool
from dormy.mcp.auth import current_user_id


def hash_key(key: str) -> str:
    """SHA256 of key, first 32 hex chars. Stored in users.api_key column."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


async def resolve_or_create_user(key: str) -> UUID:
    """Hash key, look up users by api_key. Lazy-create row if not found.

    Returns user_id UUID for attribution (e.g. user_observations.user_id).

    Race-safe: if a concurrent request inserts between our SELECT and
    INSERT, the second INSERT becomes a DO NOTHING and we re-SELECT.
    """
    key_hash = hash_key(key)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM users WHERE api_key = $1",
            key_hash,
        )
        if row:
            return row["id"]

        synthetic_email = f"byok-{key_hash[:12]}@dormy.local"
        row = await conn.fetchrow(
            """
            INSERT INTO users (email, api_key)
            VALUES ($1, $2)
            ON CONFLICT (api_key) DO NOTHING
            RETURNING id
            """,
            synthetic_email,
            key_hash,
        )
        if row:
            logger.info(
                f"BYOK lazy-created user {row['id']} for key hash {key_hash[:12]}…"
            )
            return row["id"]

        # Race: another request inserted the same hash between our SELECT and INSERT.
        row = await conn.fetchrow(
            "SELECT id FROM users WHERE api_key = $1",
            key_hash,
        )
        if not row:
            raise RuntimeError(
                f"Failed to resolve or create user for key hash {key_hash[:12]}…"
            )
        return row["id"]


def get_current_user_id() -> UUID | None:
    """Return user_id for the current execution context.

    Resolution:
      1. ContextVar set by BYOKMiddleware on HTTP request.
      2. settings.user_id (CLI / stdio fallback) parsed as UUID.

    None if neither is available — callers must decide whether to fail loudly,
    skip work (extractor returns early), or attribute to a default user.
    """
    cur = current_user_id.get()
    if cur is not None:
        return cur

    if settings.user_id:
        try:
            return UUID(settings.user_id)
        except ValueError:
            logger.warning(
                f"DORMY_USER_ID is not a valid UUID: {settings.user_id!r}"
            )
    return None
