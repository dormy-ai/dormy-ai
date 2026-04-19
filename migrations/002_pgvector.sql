-- Dormy v0.1 pgvector schema — for RAG knowledge base (dormy_memory_recall).

create extension if not exists vector;

-- ============================================================================
-- Knowledge chunks — embeddings of Newsletter + Obsidian + conversation memory
-- ============================================================================

create table if not exists knowledge_chunks (
    id           bigserial primary key,
    user_id      uuid references users(id) on delete cascade,   -- null = public
    source       text,                                          -- 'fletch_pmm' | 'obsidian' | 'startups_gallery' | 'conversation' | ...
    source_path  text,                                          -- file path / URL for dedup
    title        text,
    content      text not null,
    tags         text[],
    embedding    vector(1536),                                  -- text-embedding-3-small
    created_at   timestamptz default now()
);

-- IVFFlat index for fast cosine similarity search.
-- With small data (<100k chunks), this is overkill but future-proof.
create index if not exists idx_knowledge_embedding
    on knowledge_chunks using ivfflat (embedding vector_cosine_ops)
    with (lists = 100);

create index if not exists idx_knowledge_user_source
    on knowledge_chunks(user_id, source);

create index if not exists idx_knowledge_tags
    on knowledge_chunks using gin(tags);

-- Dedup constraint (same user + same source_path = one chunk set)
-- Actually we chunk each doc into multiple rows, so dedup happens at doc level in app logic.
