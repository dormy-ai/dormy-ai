-- Dormy v0.1 initial schema
-- Applied against Supabase Postgres.

-- ============================================================================
-- Users + auth
-- ============================================================================

create table if not exists users (
    id                    uuid primary key default gen_random_uuid(),
    email                 text unique not null,
    stripe_customer_id    text,
    api_key               text unique not null,   -- dormy_sk_xxx
    telegram_chat_id      text,                   -- for watcher push
    created_at            timestamptz default now()
);

-- ============================================================================
-- Credits ledger — event-sourced, atomic deduction
-- ============================================================================

create table if not exists credits_ledger (
    id           bigserial primary key,
    user_id      uuid references users(id) on delete cascade,
    delta_cents  int not null,                    -- positive = topup, negative = charge
    reason       text not null,                   -- 'topup_stripe' | 'tool:find_investors' | 'refund' | ...
    ref_id       text,                            -- stripe invoice id / tool call id
    created_at   timestamptz default now()
);
create index if not exists idx_credits_ledger_user_time
    on credits_ledger(user_id, created_at desc);

-- ============================================================================
-- Founder profile
-- ============================================================================

create table if not exists founder_profile (
    user_id      uuid primary key references users(id) on delete cascade,
    product_json jsonb,
    stage        text,                            -- pre-seed | seed | A | B | growth
    sector       text[],
    updated_at   timestamptz default now()
);

-- ============================================================================
-- Contacts — unified VC + angel + GTM advisor + operator table
-- Inner Circle vs public vs discovered via `tier`
-- ============================================================================

create table if not exists contacts (
    id                uuid primary key default gen_random_uuid(),
    name              text not null,
    role              text not null,              -- vc | angel | gtm-advisor | operator | founder-peer
    tier              text default 'public',      -- inner | public | discovered
    firm              text,
    email             text,
    thesis            text,
    sectors           text[],
    stages            text[],
    recent_rounds     jsonb,
    red_flags         jsonb,
    linkedin_url      text,
    twitter_url       text,
    personal_notes    text,                       -- 🌟 Pro-tier only
    warm_intro_path   text,                       -- 🌟 Pro-tier only
    tags              text[],
    added_by          uuid references users(id),  -- v0.1 admin only
    source_url        text,
    updated_at        timestamptz default now()
);
create index if not exists idx_contacts_tier_role on contacts(tier, role);
create index if not exists idx_contacts_sectors on contacts using gin(sectors);
create index if not exists idx_contacts_stages on contacts using gin(stages);
create index if not exists idx_contacts_tags on contacts using gin(tags);

-- ============================================================================
-- Match results — log of dormy_find_investors calls
-- ============================================================================

create table if not exists match_results (
    id           uuid primary key default gen_random_uuid(),
    user_id      uuid references users(id) on delete cascade,
    contact_id   uuid references contacts(id) on delete cascade,
    score        float,
    rationale    text,
    source_tier  text,                            -- copy of contact.tier at match time
    created_at   timestamptz default now()
);

-- ============================================================================
-- Watchers — dormy_watch_vcs registrations
-- ============================================================================

create table if not exists watchers (
    id            uuid primary key default gen_random_uuid(),
    user_id       uuid references users(id) on delete cascade,
    query         text not null,
    cadence       text default 'daily',           -- daily | weekly
    channels      text[] default '{email}',       -- email | telegram
    last_run_at   timestamptz,
    active        boolean default true
);
create index if not exists idx_watchers_active_lastrun on watchers(active, last_run_at);

-- ============================================================================
-- Usage log — per-tool cost + markup record (for observability + billing audit)
-- ============================================================================

create table if not exists usage_log (
    id              bigserial primary key,
    user_id         uuid references users(id) on delete cascade,
    tool            text,                         -- MCP tool name
    model           text,                         -- underlying LLM used
    tokens_in       int,
    tokens_out      int,
    cost_cents      int,                          -- actual LLM cost
    charged_cents   int,                          -- cost * 1.05 (markup)
    created_at      timestamptz default now()
);
create index if not exists idx_usage_user_time on usage_log(user_id, created_at desc);
