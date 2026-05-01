-- Dormy v0.9 — Telegram BYOK: per-user OpenRouter key.
--
-- Each Telegram user binds their own OpenRouter key via /setkey;
-- bot's _message_handler reads it and routes LLM calls (run_skill,
-- _llm_reply, gtm_*, extractor) through that key via the existing
-- current_user_key ContextVar. Server stops paying.
--
-- v0.1 stores plaintext — Supabase encrypts at rest, only DB-authorized
-- principals can read. v0.2 plan: switch to pgp_sym_encrypt with
-- DORMY_DB_ENCRYPTION_KEY before opening to non-admin users.
--
-- Lifecycle:
--   /setkey  → validate via OpenRouter /api/v1/auth/key, write column
--   /whoami  → display masked key + last validation timestamp
--   /clearkey → set NULL

alter table users
    add column if not exists openrouter_api_key text;

alter table users
    add column if not exists openrouter_key_set_at timestamptz;
