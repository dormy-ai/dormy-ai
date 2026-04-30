"""Observability layer for Dormy tools (Telegram + MCP surfaces).

Three components:
- `tool_log` — async fire-and-forget Supabase writer. Every tool dispatch
  (success or fail) writes a row to `tool_call_log`.
- `alerts` — rolling-window error detector + Telegram DM sender. 3+ same-tool
  errors within 5 min triggers an alert; 1-hour cooldown per alert key.
- `digest` — weekly summary builder + scheduled sender. Runs in the
  dormy-tg process via an asyncio loop; configurable via
  DORMY_DIGEST_FREQUENCY (weekly default).

Goal: stop silent failures. When Tavily quota dies or OpenRouter 401s,
the admin gets a Telegram DM within 5 min instead of finding out from
a confused founder.
"""

from __future__ import annotations

from dormy.telemetry.alerts import alert_unhandled_exception, maybe_alert_on_error
from dormy.telemetry.tool_log import log_tool_call

__all__ = [
    "alert_unhandled_exception",
    "log_tool_call",
    "maybe_alert_on_error",
]
