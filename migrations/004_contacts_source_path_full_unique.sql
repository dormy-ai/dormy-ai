-- Fix: ON CONFLICT (source_path) requires a full (non-partial) UNIQUE index.
-- Migration 003 created a partial index (WHERE source_path IS NOT NULL) which
-- Postgres's ON CONFLICT inference doesn't match unless the predicate is
-- repeated at the call site. Simpler to use a full unique index — every
-- ingest-generated row has a source_path anyway.

drop index if exists idx_contacts_source_path;

create unique index if not exists idx_contacts_source_path
    on contacts (source_path);
