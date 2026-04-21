"""Ingest Obsidian knowledge (Fundraising/, GTM/, Playbooks/) into Supabase
`knowledge_chunks` table with pgvector embeddings.

Excludes:
- Network/** (handled by `ingest.sync_contacts_from_vault`)
- Any file named TEMPLATE.md
- README.md at vault root (Dormy/README.md is folder metadata, not knowledge)

Strategy:
- Walk eligible .md files
- Parse frontmatter (may contain `dormy: private` to skip, or `tags: [...]`)
- Chunk body to ~500 tokens with 50-token overlap
- Embed in batches (or NULL if no API key)
- Per source_path: DELETE WHERE source_path=X, then INSERT new rows
  → idempotent re-sync without growing the table on each run
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import asyncpg
from loguru import logger

from dormy.config import settings
from dormy.knowledge.chunker import chunk_text
from dormy.knowledge.embedder import embed_batch, have_embeddings
from dormy.knowledge.obsidian import parse_markdown_file


# Default tag mapping by top-level folder (frontmatter can add more)
FOLDER_TAG_MAP: dict[str, list[str]] = {
    "Fundraising": ["fundraising"],
    "GTM": ["gtm"],
    "Playbooks": ["playbook"],
}

# Source identifier by first path segment (e.g. GTM/Newsletters/Fletch PMM/... → 'fletch_pmm')
NEWSLETTER_SOURCES: dict[str, str] = {
    "Fletch PMM": "fletch_pmm",
    "Growth Unhinged": "growth_unhinged",
    "Lenny's Newsletter": "lennys_newsletter",
    "Marketing Ideas": "marketing_ideas",
    "MRR Unlocked": "mrr_unlocked",
}


@dataclass(slots=True)
class KnowledgeIngestStats:
    files_scanned: int = 0
    files_skipped: int = 0
    chunks_written: int = 0
    errors: list[str] = field(default_factory=list)


def _classify(relative_path: Path) -> tuple[str, list[str]] | None:
    """Return (source, tags) for an eligible .md path, or None if skipped.

    `relative_path` is relative to the vault Dormy/ root.
    """
    parts = relative_path.parts
    if not parts or parts[0] not in FOLDER_TAG_MAP:
        return None  # only ingest Fundraising/GTM/Playbooks
    if relative_path.name == "TEMPLATE.md":
        return None

    tags = list(FOLDER_TAG_MAP[parts[0]])

    # If file is under <top>/Newsletters/<name>/..., tag with source id
    source = parts[0].lower()
    if len(parts) >= 3 and parts[1] == "Newsletters":
        nl_name = parts[2]
        source = NEWSLETTER_SOURCES.get(nl_name, nl_name.lower().replace(" ", "_"))
        tags.extend(["newsletter", source])

    return source, tags


def _iter_knowledge_files(vault_root: Path):
    """Yield (rel_path, abs_path) for each eligible knowledge file."""
    for top in FOLDER_TAG_MAP:
        top_dir = vault_root / top
        if not top_dir.is_dir():
            continue
        for md in top_dir.rglob("*.md"):
            if md.name == "TEMPLATE.md":
                continue
            rel = md.relative_to(vault_root)
            yield rel, md


async def _upsert_file_chunks(
    conn: asyncpg.Connection,
    *,
    source: str,
    source_path: str,
    title: str,
    tags: list[str],
    body: str,
    user_id: str | None,
) -> int:
    """Chunk a document, embed the chunks, replace the previous chunks for this
    source_path. Returns number of chunks written.
    """
    chunks = chunk_text(body)
    if not chunks:
        return 0

    # Embed (or get NULLs)
    embeddings = await embed_batch([c.content for c in chunks])

    # pgvector accepts string form '[0.1,0.2,...]' for vector binding — most
    # compatible with asyncpg without pgvector-asyncpg adapter
    def _to_vector_literal(vec: list[float] | None) -> str | None:
        if vec is None:
            return None
        return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"

    async with conn.transaction():
        await conn.execute(
            "DELETE FROM knowledge_chunks WHERE source_path = $1", source_path
        )
        rows = [
            (
                user_id,
                source,
                source_path,
                title,
                chunk.content,
                tags,
                _to_vector_literal(emb),
            )
            for chunk, emb in zip(chunks, embeddings)
        ]
        await conn.executemany(
            """
            INSERT INTO knowledge_chunks
                (user_id, source, source_path, title, content, tags, embedding)
            VALUES ($1, $2, $3, $4, $5, $6, $7::vector)
            """,
            rows,
        )
    return len(chunks)


async def sync_knowledge_from_vault(
    vault_path: str | Path | None = None,
    *,
    max_files: int | None = None,
) -> KnowledgeIngestStats:
    """Walk the Dormy/ vault and sync Fundraising/GTM/Playbooks into knowledge_chunks."""
    resolved = Path(vault_path or settings.obsidian_vault_path or "")
    if not resolved.is_dir():
        raise FileNotFoundError(
            f"Vault path does not exist or is not a directory: {resolved!r}"
        )
    if not settings.database_url:
        raise RuntimeError("DORMY_DATABASE_URL not configured")

    stats = KnowledgeIngestStats()
    has_emb = have_embeddings()
    logger.info(
        f"Knowledge sync from {resolved} "
        f"(embeddings: {'ON (OpenAI text-embedding-3-small)' if has_emb else 'OFF — NULL vectors, ILIKE retrieval'})"
    )

    conn = await asyncpg.connect(settings.database_url, statement_cache_size=0)
    try:
        count = 0
        for rel_path, md_path in _iter_knowledge_files(resolved):
            if max_files and count >= max_files:
                break
            count += 1
            stats.files_scanned += 1

            classification = _classify(rel_path)
            if classification is None:
                stats.files_skipped += 1
                continue
            source, tags = classification

            frontmatter, body = parse_markdown_file(md_path)

            # Obey frontmatter opt-outs
            dormy_flag = frontmatter.get("dormy") if frontmatter else None
            if dormy_flag == "private":
                stats.files_skipped += 1
                continue

            user_id = None
            if isinstance(dormy_flag, str) and dormy_flag.startswith("user:"):
                user_id = dormy_flag.split(":", 1)[1]

            # Augment tags from frontmatter
            if frontmatter and frontmatter.get("tags"):
                extra_tags = frontmatter["tags"]
                if isinstance(extra_tags, list):
                    tags = list({*tags, *[str(t) for t in extra_tags]})

            title = (frontmatter.get("title") if frontmatter else None) or md_path.stem

            try:
                n_chunks = await _upsert_file_chunks(
                    conn,
                    source=source,
                    source_path=str(rel_path),
                    title=title,
                    tags=tags,
                    body=body,
                    user_id=user_id,
                )
                stats.chunks_written += n_chunks
                if stats.files_scanned % 100 == 0:
                    logger.info(
                        f"  progress: {stats.files_scanned} files, "
                        f"{stats.chunks_written} chunks"
                    )
            except Exception as e:
                err = f"{rel_path}: {e}"
                logger.warning(f"[error] {err}")
                stats.errors.append(err)
    finally:
        await conn.close()

    logger.success(
        f"Knowledge sync done: {stats.files_scanned} files, "
        f"{stats.files_skipped} skipped, {stats.chunks_written} chunks written, "
        f"{len(stats.errors)} errors"
    )
    return stats
