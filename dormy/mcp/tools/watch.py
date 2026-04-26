"""watch_vcs — register a proactive daily/weekly VC watcher (mock)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from dormy.memory.hooks import from_mcp_call

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


class WatcherResult(BaseModel):
    watcher_id: str
    query: str
    cadence: str
    channels: list[str]
    next_run_at: str = Field(description="ISO-8601 UTC timestamp")
    active: bool
    note: str


def register(mcp: "FastMCP") -> None:
    @mcp.tool(
        description=(
            "Register a proactive watcher that scans for VC activity matching a natural-language "
            "query (e.g. 'AI infra seed rounds this week') on a daily or weekly cadence and "
            "pushes matches via Email and/or Telegram. Pro-tier only in production. "
            "[Week 2 Step 1: returns mock watcher_id — Railway cron + Resend/Telegram push lands Week 4.]"
        ),
    )
    def watch_vcs(
        query: str = Field(
            description="Natural-language query, e.g. 'AI infra seed rounds in last 7 days'"
        ),
        cadence: str = Field(
            default="daily",
            description="'daily' | 'weekly'",
        ),
        channels: list[str] = Field(
            default=["email"],
            description="Delivery channels: any of 'email', 'telegram'",
        ),
    ) -> WatcherResult:
        watcher_id = f"wat-{uuid.uuid4().hex[:8]}"
        hours = 24 if cadence == "daily" else 168
        next_run = datetime.now(timezone.utc) + timedelta(hours=hours)

        result = WatcherResult(
            watcher_id=watcher_id,
            query=query,
            cadence=cadence,
            channels=channels,
            next_run_at=next_run.replace(microsecond=0).isoformat(),
            active=True,
            note=(
                f"⚠️ MOCK — watcher stored in memory only (not Supabase yet). "
                f"Railway cron + Resend/Telegram push land Week 4. "
                f"Configured channels: {channels}."
            ),
        )
        from_mcp_call(
            "watch_vcs",
            {"query": query, "cadence": cadence, "channels": channels},
            result,
        )
        return result
