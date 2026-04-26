"""Invite token lifecycle for the Telegram gate.

Issue:
    create_invite(email) → ensure user exists, mint random token, persist
                           in invite_codes (expires 30d), return token+URL.

Consume:
    consume_invite(token, telegram_chat_id)
        → validate (exists, unconsumed, unexpired)
        → write users.telegram_chat_id (overwrite if user re-invited)
        → mark invite_codes.consumed_at
        → return User row (id + email) for greeting

Lookup (used by every subsequent message):
    user_by_telegram_chat_id(chat_id) → User | None
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from loguru import logger

from dormy.db import get_pool

INVITE_TTL = timedelta(days=30)
BOT_USERNAME = "dormy_dev01_bot"


@dataclass(frozen=True)
class User:
    id: UUID
    email: str


def _gen_token() -> str:
    """22-char URL-safe random — fits in Telegram /start parameter (max 64)."""
    return secrets.token_urlsafe(16)


async def _ensure_user_by_email(conn, email: str) -> UUID:
    """Look up users by email; insert if absent.

    Reuses the BYOK synthetic-email convention: real emails coexist with
    `byok-<hash>@dormy.local` rows. api_key is unique-not-null in the
    schema so we generate a deterministic placeholder per email — collisions
    impossible because email is the discriminator.
    """
    row = await conn.fetchrow(
        "SELECT id FROM users WHERE email = $1",
        email,
    )
    if row:
        return row["id"]
    # api_key is NOT NULL UNIQUE; gate-only users haven't supplied a BYOK key,
    # so synthesize a stable placeholder distinct from BYOK hashes (those are
    # 32 hex chars — ours is 32 hex with a `tg-` prefix to avoid collision).
    placeholder = "tg-" + hashlib.sha256(email.encode()).hexdigest()[:29]
    row = await conn.fetchrow(
        """
        INSERT INTO users (email, api_key)
        VALUES ($1, $2)
        ON CONFLICT (email) DO UPDATE SET email = EXCLUDED.email
        RETURNING id
        """,
        email,
        placeholder,
    )
    logger.info(f"telegram-gate: created user {row['id']} for {email}")
    return row["id"]


async def create_invite(email: str) -> tuple[str, str]:
    """Create user (if needed) + invite token. Returns (token, deep_link_url)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        user_id = await _ensure_user_by_email(conn, email)
        token = _gen_token()
        expires = datetime.now(timezone.utc) + INVITE_TTL
        await conn.execute(
            """
            INSERT INTO invite_codes (token, user_id, expires_at)
            VALUES ($1, $2, $3)
            """,
            token,
            user_id,
            expires,
        )
    return token, f"https://t.me/{BOT_USERNAME}?start={token}"


async def consume_invite(token: str, telegram_chat_id: int) -> User | None:
    """Validate + consume token, bind chat_id. Returns User on success, None on failure.

    Idempotent only in the trivial sense: a second call with the same token
    returns None (already consumed). The chat_id binding side-effect is
    not rolled back if validation fails, but we only write it after the
    `consumed_at IS NULL AND expires_at > now()` guard passes.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                UPDATE invite_codes
                   SET consumed_at = now()
                 WHERE token = $1
                   AND consumed_at IS NULL
                   AND expires_at > now()
                RETURNING user_id
                """,
                token,
            )
            if row is None:
                return None
            user_row = await conn.fetchrow(
                """
                UPDATE users
                   SET telegram_chat_id = $2
                 WHERE id = $1
                RETURNING id, email
                """,
                row["user_id"],
                str(telegram_chat_id),
            )
            if user_row is None:
                return None
            return User(id=user_row["id"], email=user_row["email"])


async def user_by_telegram_chat_id(chat_id: int) -> User | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, email FROM users WHERE telegram_chat_id = $1",
            str(chat_id),
        )
    return User(id=row["id"], email=row["email"]) if row else None
