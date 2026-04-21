-- Dormy v0.1 — add source_path to contacts for idempotent upsert from Obsidian
--
-- Obsidian .md file path (relative to vault) like 'Network/Investors/alex-chen.md'
-- is stable, so we use it as the natural dedup key for sync runs.

alter table contacts
    add column if not exists source_path text;

-- Partial unique index: only enforce uniqueness when source_path is NOT NULL
-- (web-dashboard or CSV imports that don't have a path don't get blocked).
create unique index if not exists idx_contacts_source_path
    on contacts (source_path)
    where source_path is not null;
