"""Telegram BYOK — per-user OpenRouter key bound via /setkey.

Why this exists: BLUEPRINT locks BYOK as the cost model. MCP path
already does this via `BYOKMiddleware` + `current_user_key` ContextVar.
Telegram surface was using `settings.openrouter_api_key` (server-paid)
— this module closes the gap.

Flow:
  1. User issues `/setkey sk-or-v1-xxx`. Handler calls OpenRouter's
     auth introspection endpoint to validate. On success, writes the
     key + timestamp to `users.openrouter_api_key` keyed by the
     user's chat-bound row.
  2. On every subsequent message, `_message_handler` looks up the
     user's key, sets `current_user_key` ContextVar, calls _llm_reply.
     `dormy.llm.client.get_openrouter_client()` reads ContextVar so
     all LLM calls (skill, gtm, _llm_reply itself, extractor task
     spawned via create_task — ContextVar is copied to the child)
     route through the user's key.
  3. If no key bound → handler replies onboarding instructions and
     skips the LLM call entirely (zero server cost path).

Key storage is plaintext in Supabase for v0.1. Postgres at-rest
encryption + RLS-restricted access cover the threat model where the
only privileged principal is the admin (阿蓓). v0.2 switches to
pgp_sym_encrypt before opening multi-tenant access.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx
from loguru import logger

from dormy.db import get_pool

OPENROUTER_AUTH_ENDPOINT = "https://openrouter.ai/api/v1/auth/key"
KEY_PREFIX = "sk-or-v1-"


class BYOKError(Exception):
    """Raised when key validation or key persistence fails. Caller
    formats a user-facing message — never expose the raw exception text
    to the chat (might leak internal detail)."""


def mask_key(key: str | None) -> str:
    """Display-safe key. 'sk-or-v1-abcdef…wxyz' or '(none)'."""
    if not key:
        return "(none)"
    if len(key) <= 12:
        return key[:4] + "…"
    return f"{key[:12]}…{key[-4:]}"


async def validate_openrouter_key(key: str) -> dict[str, Any]:
    """Call OpenRouter's auth introspection. Returns the `data` payload
    (label, usage, limit, etc.) on success; raises BYOKError otherwise.

    Cheap (~50ms) and doesn't burn user quota — auth/key just inspects
    the bearer.
    """
    if not key.startswith(KEY_PREFIX):
        raise BYOKError(
            f"key must start with `{KEY_PREFIX}` — get one at "
            "https://openrouter.ai/keys"
        )
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                OPENROUTER_AUTH_ENDPOINT,
                headers={"Authorization": f"Bearer {key}"},
            )
    except httpx.HTTPError as e:
        raise BYOKError(f"can't reach OpenRouter ({e})") from e

    if resp.status_code == 401 or resp.status_code == 403:
        raise BYOKError("OpenRouter rejected the key (invalid or revoked)")
    if resp.status_code >= 400:
        raise BYOKError(f"OpenRouter returned HTTP {resp.status_code}")

    try:
        body = resp.json()
    except ValueError:
        raise BYOKError("OpenRouter returned non-JSON response") from None

    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict):
        raise BYOKError("OpenRouter response missing `data` field")
    return data


async def set_user_key(user_id: UUID, key: str) -> None:
    """Validate then persist. Raises BYOKError on either failure;
    callers should NOT catch and retry (retrying a bad key is
    pointless and wastes the user's time)."""
    await validate_openrouter_key(key)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET openrouter_api_key = $1, openrouter_key_set_at = now() "
            "WHERE id = $2",
            key,
            user_id,
        )


async def get_user_key(user_id: UUID) -> str | None:
    """Return the stored key, or None if unset."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT openrouter_api_key FROM users WHERE id = $1",
            user_id,
        )


async def clear_user_key(user_id: UUID) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET openrouter_api_key = NULL, openrouter_key_set_at = NULL "
            "WHERE id = $1",
            user_id,
        )


async def get_key_metadata(user_id: UUID) -> dict[str, Any] | None:
    """For /whoami — masked key + when it was set + (optional) live
    OpenRouter usage. Returns None if no key bound."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT openrouter_api_key, openrouter_key_set_at FROM users "
            "WHERE id = $1",
            user_id,
        )
    if not row or not row["openrouter_api_key"]:
        return None
    out: dict[str, Any] = {
        "masked": mask_key(row["openrouter_api_key"]),
        "set_at": row["openrouter_key_set_at"],
    }
    # Best-effort live introspection — show usage if OpenRouter is
    # reachable, fail silent otherwise (don't make /whoami brittle).
    try:
        live = await validate_openrouter_key(row["openrouter_api_key"])
        out["label"] = live.get("label")
        out["usage"] = live.get("usage")
        out["limit"] = live.get("limit")
        out["is_free_tier"] = live.get("is_free_tier")
    except BYOKError as e:
        logger.warning(f"/whoami live check failed for user {user_id}: {e}")
        out["live_error"] = str(e)
    return out
