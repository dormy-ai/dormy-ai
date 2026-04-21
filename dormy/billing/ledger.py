"""Credits ledger — event-sourced atomic charge + topup.

Correctness strategy: per-user serialization via `SELECT ... FOR UPDATE` on
`users(id)` row inside a transaction. All balance reads and inserts into
`credits_ledger` happen under that lock, preventing:
- negative balance (two concurrent charges on thin balance)
- phantom double-spend (insert read-after-write anomalies)

v0.1 does single-phase charge: atomic check + deduct + insert. The two-phase
`reserve → commit/refund` pattern is left for Week 4 when MCP tools need to
roll back on failure; single-phase is enough for the 100-concurrent test.
"""

from __future__ import annotations

from dataclasses import dataclass

import asyncpg
from loguru import logger


class InsufficientCredits(Exception):
    """Raised when a user's balance cannot cover the requested charge."""


@dataclass(slots=True)
class ChargeResult:
    user_id: str
    charged_cents: int
    new_balance_cents: int
    ledger_id: int


async def get_balance(conn: asyncpg.Connection, user_id: str) -> int:
    """Return the user's current balance in cents (may be 0 or negative transiently)."""
    balance = await conn.fetchval(
        "SELECT COALESCE(SUM(delta_cents), 0) FROM credits_ledger WHERE user_id = $1",
        user_id,
    )
    return int(balance)


async def topup(
    conn: asyncpg.Connection,
    *,
    user_id: str,
    cents: int,
    ref_id: str | None = None,
    reason: str = "topup_stripe",
) -> ChargeResult:
    """Credit the user's account. `cents` must be positive.

    Run inside a transaction in caller if you need atomicity with other writes;
    otherwise this is a single INSERT.
    """
    if cents <= 0:
        raise ValueError("topup amount must be positive")

    row = await conn.fetchrow(
        """
        INSERT INTO credits_ledger (user_id, delta_cents, reason, ref_id)
        VALUES ($1, $2, $3, $4)
        RETURNING id
        """,
        user_id,
        cents,
        reason,
        ref_id,
    )
    balance = await get_balance(conn, user_id)
    return ChargeResult(
        user_id=user_id,
        charged_cents=cents,
        new_balance_cents=balance,
        ledger_id=row["id"],
    )


async def charge(
    pool: asyncpg.Pool,
    *,
    user_id: str,
    cents: int,
    reason: str,
    ref_id: str | None = None,
) -> ChargeResult:
    """Atomically deduct `cents` from user's balance.

    Raises InsufficientCredits if balance < cents.

    Takes a pool (not a conn) because we need our own transaction with the
    user-row lock held for the entire check+insert sequence.
    """
    if cents <= 0:
        raise ValueError("charge amount must be positive")

    async with pool.acquire() as conn:
        async with conn.transaction():
            # Row lock on users(id) serializes all balance ops for this user.
            user_row = await conn.fetchrow(
                "SELECT id FROM users WHERE id = $1 FOR UPDATE",
                user_id,
            )
            if user_row is None:
                raise ValueError(f"user {user_id} not found")

            balance = await get_balance(conn, user_id)
            if balance < cents:
                raise InsufficientCredits(
                    f"balance {balance}¢ < requested {cents}¢ for user {user_id}"
                )

            row = await conn.fetchrow(
                """
                INSERT INTO credits_ledger (user_id, delta_cents, reason, ref_id)
                VALUES ($1, $2, $3, $4)
                RETURNING id
                """,
                user_id,
                -cents,
                reason,
                ref_id,
            )
            new_balance = balance - cents

    logger.debug(
        f"charge user={user_id[:8]}.. -{cents}¢ reason={reason} → new_balance={new_balance}¢"
    )
    return ChargeResult(
        user_id=user_id,
        charged_cents=cents,
        new_balance_cents=new_balance,
        ledger_id=row["id"],
    )
