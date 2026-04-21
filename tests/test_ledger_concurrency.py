"""Concurrency test for credits ledger.

Skipped if DORMY_DATABASE_URL is not set (keeps `pytest` green for folks who
don't want a live DB). When it runs, it creates a throwaway user, tops up
100¢, fires 100 concurrent 1¢ charges, and asserts no negative balance and
exactly 100 successful charges.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import asyncpg
import pytest

from dormy.billing.ledger import (
    ChargeResult,
    InsufficientCredits,
    charge,
    get_balance,
    topup,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("DORMY_DATABASE_URL"),
    reason="DORMY_DATABASE_URL not set — skipping DB-backed test",
)


async def _make_pool() -> asyncpg.Pool:
    return await asyncpg.create_pool(
        os.environ["DORMY_DATABASE_URL"],
        min_size=2,
        max_size=10,
        statement_cache_size=0,
    )


async def _create_test_user(pool: asyncpg.Pool) -> str:
    """Insert a throwaway user; caller is responsible for cleanup."""
    email = f"ledger-test-{uuid.uuid4().hex[:8]}@example.invalid"
    api_key = f"dormy_sk_test_{uuid.uuid4().hex}"
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO users (email, api_key) VALUES ($1, $2) RETURNING id",
            email,
            api_key,
        )
    return str(row["id"])


async def _cleanup(pool: asyncpg.Pool, user_id: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM credits_ledger WHERE user_id = $1", user_id
        )
        await conn.execute("DELETE FROM users WHERE id = $1", user_id)


@pytest.mark.asyncio
async def test_100_concurrent_charges_no_negative_balance() -> None:
    pool = await _make_pool()
    user_id = await _create_test_user(pool)

    try:
        # Fund with exactly 100¢
        async with pool.acquire() as conn:
            await topup(conn, user_id=user_id, cents=100, ref_id="test-seed")
            initial = await get_balance(conn, user_id)
        assert initial == 100

        # Fire 100 concurrent charges of 1¢ each
        async def _one() -> ChargeResult | InsufficientCredits:
            try:
                return await charge(
                    pool, user_id=user_id, cents=1, reason="test:concurrent"
                )
            except InsufficientCredits as e:
                return e

        results = await asyncio.gather(*[_one() for _ in range(100)])

        successes = [r for r in results if isinstance(r, ChargeResult)]
        failures = [r for r in results if isinstance(r, InsufficientCredits)]

        assert len(successes) == 100, f"expected 100 successes, got {len(successes)}"
        assert len(failures) == 0, f"unexpected failures: {failures[:3]}"

        # Final balance must be exactly 0 — no negative, no leftover.
        async with pool.acquire() as conn:
            final = await get_balance(conn, user_id)
        assert final == 0, f"expected balance 0, got {final}"

        # The 101st charge must be rejected.
        with pytest.raises(InsufficientCredits):
            await charge(pool, user_id=user_id, cents=1, reason="test:overdraw")
    finally:
        await _cleanup(pool, user_id)
        await pool.close()


@pytest.mark.asyncio
async def test_overspend_rejected_cleanly() -> None:
    """Funding 50¢ and firing 100x1¢ concurrent charges must leave balance ≥ 0
    with exactly 50 successes and 50 InsufficientCredits failures."""
    pool = await _make_pool()
    user_id = await _create_test_user(pool)

    try:
        async with pool.acquire() as conn:
            await topup(conn, user_id=user_id, cents=50, ref_id="test-seed")

        async def _one() -> ChargeResult | InsufficientCredits:
            try:
                return await charge(
                    pool, user_id=user_id, cents=1, reason="test:overspend"
                )
            except InsufficientCredits as e:
                return e

        results = await asyncio.gather(*[_one() for _ in range(100)])
        successes = sum(1 for r in results if isinstance(r, ChargeResult))
        failures = sum(1 for r in results if isinstance(r, InsufficientCredits))

        assert successes == 50, f"expected 50 successes, got {successes}"
        assert failures == 50, f"expected 50 failures, got {failures}"

        async with pool.acquire() as conn:
            final = await get_balance(conn, user_id)
        assert final == 0, f"balance must settle at 0, got {final}"
    finally:
        await _cleanup(pool, user_id)
        await pool.close()
