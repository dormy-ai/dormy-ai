"""Real-time alert engine — Telegram DM to admin on threshold breaches.

Two trigger types:
  1. Tool error burst — 3+ same-tool errors within 5 min from any source.
     Use case: Tavily quota exhausted, OpenRouter 401 from credentials drift,
     Supabase pool dying. The 3-in-5 threshold filters out single transient
     blips while catching real problems fast.
  2. Unhandled exception — anything that escapes _llm_reply's try/except
     and would otherwise just become a user-facing "I went a bit deep"
     fallback. These are rarer but always worth a heads-up.

Both kinds share a 1-hour cooldown per alert key so a sustained outage
doesn't spam the admin. State is in-memory only (no Redis); a bot
restart resets cooldowns, which is fine for v0.1.

Admin chat is set via DORMY_ALERT_CHAT_ID env. If unset, alerts are
silently skipped (still log to loguru) so the bot keeps working in dev.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque

from loguru import logger

from dormy.config import settings

# Rolling window of error timestamps per (source, tool_name).
_error_window: dict[tuple[str, str], deque[float]] = defaultdict(
    lambda: deque(maxlen=20)
)
# Cooldown — last time we DMed for this alert key (Unix epoch seconds).
_alert_cooldown: dict[str, float] = {}

ERROR_BURST_THRESHOLD = 3   # 3+ errors of same tool in window
ERROR_WINDOW_SEC = 300       # 5 min
ALERT_COOLDOWN_SEC = 3600    # 1 hour per alert key


async def _send_dm(text: str) -> None:
    """Best-effort DM to admin chat. No-op if env unset / Telegram down."""
    chat_id = settings.alert_chat_id
    token = settings.telegram_bot_token
    if not chat_id or not token:
        logger.info(
            f"alert (not sent — DORMY_ALERT_CHAT_ID/TELEGRAM_BOT_TOKEN unset): {text[:200]}"
        )
        return

    # Use a lazy import + per-call client. Keeps this module unimportable-
    # at-startup on systems without `telegram` installed; only surface
    # using the bot has it as a dep anyway.
    try:
        from telegram import Bot

        bot = Bot(token=token)
        await bot.send_message(chat_id=int(chat_id), text=text[:4000])
    except Exception as e:  # noqa: BLE001
        logger.warning(f"alert DM failed: {e}")


def _on_cooldown(key: str) -> bool:
    last = _alert_cooldown.get(key, 0)
    return (time.time() - last) < ALERT_COOLDOWN_SEC


def _stamp_cooldown(key: str) -> None:
    _alert_cooldown[key] = time.time()


async def maybe_alert_on_error(
    source: str,
    tool_name: str,
    error_msg: str | None,
) -> None:
    """Record a tool-call error and DM admin if the rolling window
    crosses the burst threshold. Caller passes already-trimmed error_msg.
    """
    key = f"{source}:{tool_name}"
    now = time.time()
    window = _error_window[key]
    window.append(now)

    # Trim outside-window entries.
    while window and (now - window[0]) > ERROR_WINDOW_SEC:
        window.popleft()

    if len(window) < ERROR_BURST_THRESHOLD:
        return
    if _on_cooldown(key):
        return

    msg = (
        f"⚠️ Dormy alert\n"
        f"{source}/{tool_name}: {len(window)} errors in last "
        f"{ERROR_WINDOW_SEC // 60}min\n"
        f"Last error: {(error_msg or '(no message)')[:300]}\n"
        f"Cooldown 1h — won't ping again about this until then."
    )
    _stamp_cooldown(key)
    # Clear window after firing so the next 3 errors after cooldown
    # trigger a fresh alert (vs the same window staying full forever).
    window.clear()
    await _send_dm(msg)


async def alert_unhandled_exception(where: str, exc: BaseException) -> None:
    """DM admin about a code path that crashed. Cooldown keyed by `where`
    so a tight retry loop doesn't carpet-bomb. Always logs the full
    traceback regardless of cooldown."""
    logger.exception(f"unhandled exception at {where}")

    key = f"exc:{where}"
    if _on_cooldown(key):
        return
    _stamp_cooldown(key)

    msg = (
        f"🔥 Dormy alert — unhandled exception\n"
        f"at: {where}\n"
        f"{type(exc).__name__}: {str(exc)[:400]}\n"
        f"Cooldown 1h."
    )
    await _send_dm(msg)


def fire_and_forget_alert_on_error(
    source: str,
    tool_name: str,
    error_msg: str | None,
) -> None:
    """Synchronous-looking wrapper: schedules maybe_alert_on_error on
    the running loop. Use this from non-async dispatch sites (e.g.
    `from_mcp_call`)."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(maybe_alert_on_error(source, tool_name, error_msg))
