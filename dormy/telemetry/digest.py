"""Periodic digest — summarizes recent tool activity, DMs admin.

Default cadence: weekly (Mondays 09:00 UTC). Admin can change via env:
  DORMY_DIGEST_FREQUENCY=weekly | daily | off

Each digest message ends with a footer reminding how to change cadence
so the user discovers the lever organically without reading docs.

Started by the dormy-tg process via `start_digest_loop()` — runs as
an asyncio task alongside the long-poll loop. No new container needed.
A bot restart skips a missed window (e.g. if container was redeploying
at 09:00 Monday); we don't backfill since digests are nice-to-have, not
critical.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from loguru import logger

from dormy.config import settings
from dormy.db import get_pool
from dormy.telemetry.alerts import _send_dm  # reuse same DM path

# 09:00 UTC = 17:00 Asia/Shanghai = 02:00 America/Los_Angeles. Reasonable
# slot for the admin to read without it pinging at 4am.
DIGEST_HOUR_UTC = 9
DIGEST_MINUTE_UTC = 0
WEEKLY_DAY_UTC = 0  # Monday (datetime.weekday: Mon=0)


def _next_run_at(frequency: str, now: datetime | None = None) -> datetime:
    """Compute the next scheduled run time in UTC for the given cadence."""
    now = now or datetime.now(timezone.utc)
    target = now.replace(
        hour=DIGEST_HOUR_UTC, minute=DIGEST_MINUTE_UTC, second=0, microsecond=0
    )
    if frequency == "daily":
        if target <= now:
            target += timedelta(days=1)
        return target
    # weekly (default) — next Monday at 09:00 UTC
    days_ahead = (WEEKLY_DAY_UTC - now.weekday()) % 7
    target = target + timedelta(days=days_ahead)
    if target <= now:
        target += timedelta(days=7)
    return target


def _window_label(frequency: str) -> tuple[str, str]:
    """Returns (interval_clause, human_label) — the SQL window + display text."""
    if frequency == "daily":
        return "interval '24 hours'", "过去 24 小时"
    return "interval '7 days'", "过去 7 天"


DIGEST_QUERY = """
SELECT
    tool_name,
    status,
    count(*) AS calls,
    avg(latency_ms)::int AS avg_ms,
    percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms)::int AS p95_ms
FROM tool_call_log
WHERE ts > now() - {interval_clause}
GROUP BY tool_name, status
ORDER BY calls DESC
LIMIT 50
"""

ERROR_QUERY = """
SELECT tool_name, error_msg, count(*) AS n
FROM tool_call_log
WHERE ts > now() - {interval_clause}
  AND status = 'error'
GROUP BY tool_name, error_msg
ORDER BY n DESC
LIMIT 5
"""


async def build_digest(frequency: str) -> str:
    """Query DB, render markdown digest. Returns empty string if no
    activity (caller can decide whether to skip sending)."""
    interval_clause, label = _window_label(frequency)
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(DIGEST_QUERY.format(interval_clause=interval_clause))
            err_rows = await conn.fetch(ERROR_QUERY.format(interval_clause=interval_clause))
    except Exception as e:  # noqa: BLE001
        logger.warning(f"digest query failed: {e}")
        return ""

    if not rows:
        return ""

    total_calls = sum(r["calls"] for r in rows)
    ok_calls = sum(r["calls"] for r in rows if r["status"] == "ok")
    err_calls = total_calls - ok_calls

    # Top tools by call count (combine ok+error per tool).
    by_tool: dict[str, dict[str, int]] = {}
    for r in rows:
        slot = by_tool.setdefault(
            r["tool_name"], {"calls": 0, "errors": 0, "avg_ms": 0, "p95_ms": 0}
        )
        slot["calls"] += r["calls"]
        if r["status"] == "error":
            slot["errors"] += r["calls"]
        # Use latency from ok rows when present; else error rows.
        if slot["avg_ms"] == 0 or r["status"] == "ok":
            slot["avg_ms"] = r["avg_ms"]
            slot["p95_ms"] = r["p95_ms"]
    top_tools = sorted(by_tool.items(), key=lambda kv: -kv[1]["calls"])[:5]

    lines = [
        f"📊 *Dormy {('每周' if frequency != 'daily' else '每日')} digest*",
        f"_{label}_",
        "",
        f"*总调用*: {total_calls}  ·  ✅ {ok_calls}  ·  ❌ {err_calls}",
        "",
        "*Top tools*:",
    ]
    for tool, stats in top_tools:
        err_part = f" · ❌ {stats['errors']}" if stats["errors"] else ""
        lines.append(
            f"  • `{tool}`: {stats['calls']} calls"
            f"{err_part} · avg {stats['avg_ms']}ms · p95 {stats['p95_ms']}ms"
        )

    if err_rows:
        lines.append("")
        lines.append("*Top errors*:")
        for r in err_rows:
            short = (r["error_msg"] or "(no message)")[:100]
            lines.append(f"  • `{r['tool_name']}` ×{r['n']}: {short}")

    lines.append("")
    lines.append(
        f"_频率: {frequency}_ · 改成 daily / weekly / off:"
        " 设 `DORMY_DIGEST_FREQUENCY` env"
    )

    return "\n".join(lines)


async def send_digest(frequency: str) -> None:
    """Build + send. No-op if no activity."""
    body = await build_digest(frequency)
    if not body:
        logger.info(f"digest ({frequency}): no activity — skipping")
        return
    await _send_dm(body)


async def digest_loop(frequency: str) -> None:
    """Sleep until next scheduled run, send, repeat."""
    if frequency not in ("daily", "weekly"):
        logger.info(f"digest disabled (frequency={frequency!r})")
        return
    while True:
        next_run = _next_run_at(frequency)
        seconds = (next_run - datetime.now(timezone.utc)).total_seconds()
        logger.info(
            f"digest ({frequency}): next run at {next_run.isoformat()} "
            f"(in {seconds / 3600:.1f}h)"
        )
        try:
            await asyncio.sleep(max(1, seconds))
            await send_digest(frequency)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.warning(f"digest loop iteration error: {e}")
            # Sleep an hour before next attempt so we don't tight-loop
            # on a persistent DB error.
            await asyncio.sleep(3600)


def start_digest_loop() -> asyncio.Task | None:
    """Schedule the digest loop on the current event loop. Returns the
    Task so the caller can cancel on shutdown. Returns None if digest
    is disabled."""
    frequency = settings.digest_frequency or "weekly"
    if frequency == "off":
        logger.info("digest: disabled via DORMY_DIGEST_FREQUENCY=off")
        return None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("digest: no running loop — skipping schedule")
        return None
    return loop.create_task(digest_loop(frequency))
