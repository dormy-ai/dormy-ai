-- Dormy v0.2 — split GTM advisors into their own table.
--
-- Why: investor and GTM are two different funnels. Investor rows have
-- stages + recent_rounds (funding-cycle data); GTM rows do not, and will
-- want their own future fields (services / engagement_model / pricing_tier).
-- Keeping them in one `contacts` table forces every column to be nullable
-- and every query to filter by role. Splitting now is cheaper than later.
--
-- Vault layout in dormy-trainer:
--   Network/Investors/*.md  →  contacts        (role: vc | angel)
--   Network/GTM/*.md        →  gtm_advisors    (role: gtm-advisor | operator | founder-peer)

create table if not exists gtm_advisors (
    id                uuid primary key default gen_random_uuid(),
    name              text not null,
    role              text not null,                  -- gtm-advisor | operator | founder-peer
    tier              text default 'inner',           -- inner | public | discovered
    firm              text,
    email             text,
    sectors           text[],                         -- focus areas (kept for filter parity)
    linkedin_url      text,
    twitter_url       text,
    personal_notes    text,                           -- 🌟 Pro-tier only
    warm_intro_path   text,                           -- 🌟 Pro-tier only
    recent_activity   jsonb,                          -- mirrors contacts.recent_rounds slot
    red_flags         jsonb,
    tags              text[],
    source_path       text,                           -- Network/GTM/<slug>.md, natural dedup key
    added_by          uuid references users(id),
    updated_at        timestamptz default now()
);

-- Full unique index (not partial) so ON CONFLICT (source_path) inference works,
-- following the pattern set by migration 004 for contacts.
create unique index if not exists idx_gtm_advisors_source_path on gtm_advisors (source_path);
create index if not exists idx_gtm_advisors_tier_role on gtm_advisors (tier, role);
create index if not exists idx_gtm_advisors_sectors on gtm_advisors using gin (sectors);
create index if not exists idx_gtm_advisors_tags on gtm_advisors using gin (tags);

-- ============================================================================
-- Data migration: move existing GTM rows out of contacts → gtm_advisors.
-- recent_rounds (jsonb) maps to recent_activity (jsonb) — same payload,
-- renamed to match GTM frontmatter semantics.
-- ============================================================================

insert into gtm_advisors (
    id, name, role, tier, firm, email, sectors, linkedin_url, twitter_url,
    personal_notes, warm_intro_path, recent_activity, red_flags, tags,
    source_path, added_by, updated_at
)
select
    id, name, role, tier, firm, email, sectors, linkedin_url, twitter_url,
    personal_notes, warm_intro_path, recent_rounds, red_flags, tags,
    source_path, added_by, updated_at
from contacts
where role in ('gtm-advisor', 'operator', 'founder-peer')
on conflict (source_path) do nothing;

delete from contacts
where role in ('gtm-advisor', 'operator', 'founder-peer');
