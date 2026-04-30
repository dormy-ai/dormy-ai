-- Dormy v0.8 — tool_call_log: per-call observability for Telegram + MCP surfaces.
--
-- Every tool dispatch (web_search, run_skill, recent_funding, fetch_page,
-- find_investors, etc.) writes one row here. Async fire-and-forget from the
-- bot loop / MCP wrapper, so a DB hiccup doesn't break user replies.
--
-- Used by:
--   1. Real-time alert engine (dormy/telemetry/alerts.py) — checks rolling
--      5-min window per (source, tool_name); 3+ errors triggers Telegram DM.
--   2. Daily digest (dormy/telemetry/digest.py) — 09:00 UTC summary of
--      yesterday's activity sent to admin chat.
--   3. Ad-hoc Supabase Studio queries (top errors, latency p95, busiest tool).

create table if not exists tool_call_log (
    id            bigserial primary key,
    ts            timestamptz not null default now(),
    source        text not null,                   -- 'telegram' | 'mcp'
    tool_name     text not null,                   -- 'web_search', 'run_skill', etc.
    status        text not null check (status in ('ok', 'error')),
    latency_ms    integer not null,
    error_msg     text,                            -- nullable; full error text on failure
    args          jsonb,                           -- truncated arg snapshot for debugging
    user_id       uuid,                            -- nullable when chat unbound
    chat_id_hash  text                             -- nullable; sha256 of telegram chat_id (privacy)
);

-- Hot path: alert engine queries last 5 min by tool.
create index if not exists idx_tool_call_log_ts_tool
    on tool_call_log (ts desc, tool_name);

-- Errors-only index for digest "top error types" + alerts.
create index if not exists idx_tool_call_log_errors
    on tool_call_log (ts desc, tool_name)
    where status = 'error';
