"""Async fire-and-forget writer for tool_call_log.

Called from `dormy.telegram.tools.execute_tool` and `dormy.memory.hooks.from_mcp_call`
on every tool dispatch. Doesn't block the calling code path — uses
`asyncio.create_task` so a slow Supabase write doesn't make the user
wait. If the DB write fails, log it and continue; we never want
observability to break the product.

Schema in `migrations/008_tool_call_log.sql`.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any
from uuid import UUID

from loguru import logger

from dormy.db import get_pool

ARGS_CAP_CHARS = 2000  # truncate args before storing — most are tiny but
                      # run_skill input can be a multi-paragraph context

INSERT_SQL = """
INSERT INTO tool_call_log
    (source, tool_name, status, latency_ms, error_msg, args, user_id, chat_id_hash)
VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8)
"""


def _hash_chat_id(chat_id: int | str | None) -> str | None:
    """SHA256 of chat_id for privacy. Reversible with rainbow table only
    if the attacker has the source chat_id, which is fine — we just want
    to avoid storing raw IDs in the log table."""
    if chat_id is None:
        return None
    return hashlib.sha256(str(chat_id).encode("utf-8")).hexdigest()[:32]


def _truncate_args(args: dict[str, Any] | None) -> str | None:
    """JSON-serialize + cap length. Returns None if args is None/empty."""
    if not args:
        return None
    try:
        s = json.dumps(args, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return None
    if len(s) > ARGS_CAP_CHARS:
        s = s[:ARGS_CAP_CHARS] + '..."}'
        # Try parsing again after truncation; if invalid JSON, store as
        # a wrapped string so the column type isn't violated.
        try:
            json.loads(s)
        except json.JSONDecodeError:
            s = json.dumps({"_truncated": s[:ARGS_CAP_CHARS]})
    return s


async def _do_insert(
    source: str,
    tool_name: str,
    status: str,
    latency_ms: int,
    error_msg: str | None,
    args_json: str | None,
    user_id: UUID | None,
    chat_id_hash: str | None,
) -> None:
    """Actual DB insert — wrapped so the calling path can fire-and-forget."""
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                INSERT_SQL,
                source,
                tool_name,
                status,
                latency_ms,
                error_msg,
                args_json,
                user_id,
                chat_id_hash,
            )
    except Exception as e:  # noqa: BLE001
        # NEVER raise from telemetry — log and move on. Observability
        # outage must not become a product outage.
        logger.warning(f"tool_log insert failed for {tool_name}: {e}")


def log_tool_call(
    source: str,
    tool_name: str,
    status: str,
    latency_ms: int,
    error_msg: str | None = None,
    args: dict[str, Any] | None = None,
    user_id: UUID | None = None,
    chat_id: int | str | None = None,
) -> None:
    """Schedule an insert into tool_call_log. Returns immediately.

    Intentionally synchronous-looking — wraps `asyncio.create_task` so
    the caller doesn't need to await. If there's no running loop (e.g.
    in unit tests), drops the call with a debug log.
    """
    if status not in ("ok", "error"):
        logger.warning(f"tool_log: invalid status {status!r}, coercing to 'error'")
        status = "error"

    args_json = _truncate_args(args)
    chat_id_hash = _hash_chat_id(chat_id)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug(
            f"tool_log: no running loop — skipping insert for {source}/{tool_name}"
        )
        return

    loop.create_task(
        _do_insert(
            source=source,
            tool_name=tool_name,
            status=status,
            latency_ms=latency_ms,
            error_msg=error_msg,
            args_json=args_json,
            user_id=user_id,
            chat_id_hash=chat_id_hash,
        )
    )
