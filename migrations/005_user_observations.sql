-- Dormy v0.1 — user_observations: agent's evolving understanding of each founder.
-- Captured by extractor (Sonnet 4.6 batch) from conversation history. Read by
-- engine modules to inform retrieval / matching / drafting on a per-founder basis.
-- App-level user_id filtering (matches knowledge_chunks pattern; no Postgres RLS).

create table if not exists user_observations (
    id                  bigserial primary key,
    user_id             uuid not null references users(id) on delete cascade,
    observed_at         timestamptz default now(),
    source              text not null,                              -- 'telegram' | 'cli' | 'mcp'
    session_id          text,                                       -- nanobot session id or CLI invocation id

    kind                text not null check (kind in
        ('preference','fact','goal','concern','pattern')),
    tags                text[] default '{}',                        -- e.g. {'fundraising','seed','eu-market'}
    content             text not null,                              -- free-form natural language note
    confidence          real default 0.7 check (confidence >= 0 and confidence <= 1),

    source_message_ids  text[],                                     -- batch's source messages for traceability
    batch_id            uuid,                                       -- shared by all observations from same extractor run
    extracted_by_model  text default 'claude-sonnet-4-6',
    superseded_by       bigint references user_observations(id),    -- newer observation invalidating this

    embedding           vector(1536)                                -- text-embedding-3-small (matches knowledge_chunks)
);

-- Recency-first lookup per founder
create index if not exists idx_user_observations_user_time
    on user_observations(user_id, observed_at desc);

-- Tag-based filter (e.g. "show me everything tagged 'fundraising'")
create index if not exists idx_user_observations_tags
    on user_observations using gin(tags);

-- Kind-scoped lookup (e.g. only goals, only concerns)
create index if not exists idx_user_observations_kind
    on user_observations(user_id, kind);

-- Semantic retrieval via cosine similarity on embedding
create index if not exists idx_user_observations_embedding
    on user_observations using ivfflat (embedding vector_cosine_ops)
    with (lists = 100);
