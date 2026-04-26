-- Dormy v0.6 — Telegram bot invite gate.
--
-- One-time-use tokens that bind a Telegram chat_id to a Dormy users row.
-- Issued via `dormy invite create <email>` after manual lead review;
-- consumed when the user clicks the deep link `t.me/dormy_dev01_bot?start=<token>`.
--
-- Lifecycle:
--   1. CLI inserts row { token, user_id, expires_at = now() + 30d }
--   2. Bot's /start <token> handler validates token (exists, not consumed,
--      not expired), writes users.telegram_chat_id, marks consumed_at.
--   3. Subsequent messages from that chat_id resolve user_id via
--      `users.telegram_chat_id` lookup — no further token use.

create table if not exists invite_codes (
    token         text primary key,
    user_id       uuid not null references users(id) on delete cascade,
    created_at    timestamptz not null default now(),
    consumed_at   timestamptz,
    expires_at    timestamptz not null
);

-- Active (not yet consumed) tokens by user, used by CLI to dedupe.
create index if not exists idx_invite_codes_user_active
    on invite_codes(user_id) where consumed_at is null;
