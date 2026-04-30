"""Tests for dormy.telemetry — tool_log, alerts, digest.

DB-touching paths covered via end-to-end on production. Unit tests
pin: alert thresholds + cooldown, digest schedule math, log writer
graceful no-loop fallback, hash determinism.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import pytest

from dormy.telemetry import alerts as alerts_mod
from dormy.telemetry.alerts import (
    ALERT_COOLDOWN_SEC,
    ERROR_BURST_THRESHOLD,
    ERROR_WINDOW_SEC,
    maybe_alert_on_error,
)
from dormy.telemetry.digest import _next_run_at, _window_label
from dormy.telemetry.tool_log import _hash_chat_id, _truncate_args, log_tool_call


# --- tool_log ---


def test_hash_chat_id_deterministic_and_short() -> None:
    a = _hash_chat_id(12345)
    b = _hash_chat_id(12345)
    c = _hash_chat_id(99999)
    assert a == b
    assert a != c
    assert a is not None and len(a) == 32  # truncated SHA256


def test_hash_chat_id_handles_none() -> None:
    assert _hash_chat_id(None) is None


def test_truncate_args_handles_empty() -> None:
    assert _truncate_args(None) is None
    assert _truncate_args({}) is None


def test_truncate_args_returns_json_for_short_dict() -> None:
    out = _truncate_args({"q": "hi", "n": 3})
    assert out is not None and "hi" in out and "3" in out


def test_truncate_args_caps_long_input() -> None:
    out = _truncate_args({"input": "x" * 5000})
    assert out is not None
    assert len(out) <= 2200  # ARGS_CAP_CHARS=2000 + small JSON overhead


def test_log_tool_call_no_loop_is_safe() -> None:
    """Outside an async context (unit test sync), this must NOT raise."""
    log_tool_call(
        source="telegram",
        tool_name="web_search",
        status="ok",
        latency_ms=42,
        args={"query": "x"},
    )
    # If we get here, no exception leaked. That's the assertion.


def test_log_tool_call_invalid_status_coerced() -> None:
    """Status 'pending' is invalid — should coerce to 'error' (logged)
    rather than raise."""
    log_tool_call(
        source="telegram",
        tool_name="web_search",
        status="pending",  # type: ignore[arg-type]
        latency_ms=1,
    )


# --- alerts ---


def _reset_alert_state() -> None:
    alerts_mod._error_window.clear()
    alerts_mod._alert_cooldown.clear()


@pytest.mark.asyncio
async def test_first_two_errors_dont_alert(monkeypatch) -> None:
    """Below threshold = no DM."""
    _reset_alert_state()
    sent: list[str] = []

    async def fake_send(text: str) -> None:
        sent.append(text)

    monkeypatch.setattr(alerts_mod, "_send_dm", fake_send)
    await maybe_alert_on_error("telegram", "web_search", "boom 1")
    await maybe_alert_on_error("telegram", "web_search", "boom 2")
    assert sent == []


@pytest.mark.asyncio
async def test_third_error_in_window_alerts(monkeypatch) -> None:
    _reset_alert_state()
    sent: list[str] = []

    async def fake_send(text: str) -> None:
        sent.append(text)

    monkeypatch.setattr(alerts_mod, "_send_dm", fake_send)
    for i in range(ERROR_BURST_THRESHOLD):
        await maybe_alert_on_error("telegram", "web_search", f"boom {i}")
    assert len(sent) == 1
    assert "web_search" in sent[0]
    assert "errors in last" in sent[0].lower() or "5min" in sent[0]


@pytest.mark.asyncio
async def test_cooldown_prevents_double_alert(monkeypatch) -> None:
    _reset_alert_state()
    sent: list[str] = []

    async def fake_send(text: str) -> None:
        sent.append(text)

    monkeypatch.setattr(alerts_mod, "_send_dm", fake_send)
    # First burst — fires.
    for i in range(ERROR_BURST_THRESHOLD):
        await maybe_alert_on_error("telegram", "web_search", f"boom {i}")
    # Second burst inside cooldown — silent.
    for i in range(ERROR_BURST_THRESHOLD):
        await maybe_alert_on_error("telegram", "web_search", f"boom {i + 10}")
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_different_tools_have_independent_keys(monkeypatch) -> None:
    _reset_alert_state()
    sent: list[str] = []

    async def fake_send(text: str) -> None:
        sent.append(text)

    monkeypatch.setattr(alerts_mod, "_send_dm", fake_send)
    for i in range(ERROR_BURST_THRESHOLD):
        await maybe_alert_on_error("telegram", "web_search", f"a{i}")
    for i in range(ERROR_BURST_THRESHOLD):
        await maybe_alert_on_error("telegram", "fetch_page", f"b{i}")
    assert len(sent) == 2  # one per (source, tool)


@pytest.mark.asyncio
async def test_old_errors_purged_from_window(monkeypatch) -> None:
    """If errors arrived more than 5 min ago, they shouldn't count."""
    _reset_alert_state()
    sent: list[str] = []

    async def fake_send(text: str) -> None:
        sent.append(text)

    monkeypatch.setattr(alerts_mod, "_send_dm", fake_send)

    # Plant 2 expired errors directly in the window.
    key = ("telegram", "web_search")
    long_ago = time.time() - ERROR_WINDOW_SEC - 100
    alerts_mod._error_window[key].append(long_ago)
    alerts_mod._error_window[key].append(long_ago + 1)

    # One fresh error — total in window is now 1 (after purge), no alert.
    await maybe_alert_on_error("telegram", "web_search", "fresh")
    assert sent == []


def test_threshold_constants_sane() -> None:
    """Pin so accidental edits get flagged in review."""
    assert ERROR_BURST_THRESHOLD == 3
    assert ERROR_WINDOW_SEC == 300
    assert ALERT_COOLDOWN_SEC == 3600


# --- digest schedule math ---


def test_digest_window_label() -> None:
    interval, label = _window_label("daily")
    assert "24 hours" in interval
    assert "24" in label

    interval, label = _window_label("weekly")
    assert "7 days" in interval
    assert "7" in label


def test_digest_next_run_daily_today_morning_returns_today_or_tomorrow() -> None:
    # Simulate "now = today 03:00 UTC" — next daily run should be today 09:00.
    fake_now = datetime(2026, 4, 30, 3, 0, tzinfo=timezone.utc)
    nxt = _next_run_at("daily", now=fake_now)
    assert nxt == datetime(2026, 4, 30, 9, 0, tzinfo=timezone.utc)


def test_digest_next_run_daily_evening_skips_to_tomorrow() -> None:
    fake_now = datetime(2026, 4, 30, 21, 0, tzinfo=timezone.utc)
    nxt = _next_run_at("daily", now=fake_now)
    assert nxt == datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc)


def test_digest_next_run_weekly_picks_next_monday() -> None:
    # 2026-04-30 is a Thursday (weekday=3). Next Monday = 2026-05-04.
    fake_now = datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc)
    nxt = _next_run_at("weekly", now=fake_now)
    assert nxt.weekday() == 0  # Monday
    assert nxt == datetime(2026, 5, 4, 9, 0, tzinfo=timezone.utc)


def test_digest_next_run_weekly_on_monday_morning_picks_today() -> None:
    # Monday 03:00 UTC — should pick today 09:00, not next week.
    monday_morning = datetime(2026, 5, 4, 3, 0, tzinfo=timezone.utc)
    assert monday_morning.weekday() == 0
    nxt = _next_run_at("weekly", now=monday_morning)
    assert nxt == datetime(2026, 5, 4, 9, 0, tzinfo=timezone.utc)


def test_digest_next_run_weekly_on_monday_after_run_picks_next_monday() -> None:
    monday_evening = datetime(2026, 5, 4, 18, 0, tzinfo=timezone.utc)
    nxt = _next_run_at("weekly", now=monday_evening)
    assert nxt == datetime(2026, 5, 11, 9, 0, tzinfo=timezone.utc)
