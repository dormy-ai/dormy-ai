"""Knowledge ingest — Obsidian vault → Supabase contacts table.

Walks `<vault>/Network/Investors/*.md` + `<vault>/Network/Advisors/*.md`, parses
each file's YAML frontmatter + body, and upserts a row into `contacts` using
`source_path` (e.g. 'Network/Investors/alex-chen.md') as the natural dedup key.

Week 2 Step 2: `contacts` only. Knowledge-chunks RAG ingest (Fundraising/, GTM/,
Playbooks/) lands in Week 3.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import asyncpg
from loguru import logger

from dormy.config import settings
from dormy.knowledge.obsidian import parse_markdown_file


CONTACTS_SUBPATHS = ("Network/Investors", "Network/Advisors")


@dataclass(slots=True)
class IngestStats:
    scanned: int = 0
    upserted: int = 0
    skipped: int = 0


def _infer_role(source_path: str, frontmatter_role: str | None) -> str:
    """Default role by folder; frontmatter overrides if present."""
    if frontmatter_role:
        return frontmatter_role
    if "Advisors" in source_path:
        return "gtm-advisor"
    return "vc"


def _to_jsonb(value) -> str | None:
    """Serialize to a JSON string for asyncpg jsonb binding. Empty → None."""
    if value is None or value == "":
        return None
    return json.dumps(value)


async def upsert_contact(
    conn: asyncpg.Connection,
    *,
    source_path: str,
    frontmatter: dict,
) -> bool:
    """Upsert one contact. Returns True if a row was written (insert or update)."""
    name = frontmatter.get("name")
    if not name:
        logger.warning(f"[skip] {source_path}: missing 'name' in frontmatter")
        return False

    role = _infer_role(source_path, frontmatter.get("role"))
    tier = frontmatter.get("tier", "inner")  # Network/** is Inner Circle by convention

    # asyncpg needs JSON *strings* for jsonb parameters; text arrays bind natively.
    await conn.execute(
        """
        INSERT INTO contacts (
            name, role, tier, firm, email, sectors, stages,
            linkedin_url, twitter_url, personal_notes, warm_intro_path,
            tags, recent_rounds, red_flags, source_path, updated_at
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7,
                $8, $9, $10, $11,
                $12, $13::jsonb, $14::jsonb, $15, now())
        ON CONFLICT (source_path) DO UPDATE SET
            name              = EXCLUDED.name,
            role              = EXCLUDED.role,
            tier              = EXCLUDED.tier,
            firm              = EXCLUDED.firm,
            email             = EXCLUDED.email,
            sectors           = EXCLUDED.sectors,
            stages            = EXCLUDED.stages,
            linkedin_url      = EXCLUDED.linkedin_url,
            twitter_url       = EXCLUDED.twitter_url,
            personal_notes    = EXCLUDED.personal_notes,
            warm_intro_path   = EXCLUDED.warm_intro_path,
            tags              = EXCLUDED.tags,
            recent_rounds     = EXCLUDED.recent_rounds,
            red_flags         = EXCLUDED.red_flags,
            updated_at        = now()
        """,
        name,
        role,
        tier,
        frontmatter.get("firm"),
        frontmatter.get("email"),
        list(frontmatter.get("sectors") or []),
        list(frontmatter.get("stages") or []),
        frontmatter.get("linkedin_url"),
        frontmatter.get("twitter_url"),
        frontmatter.get("personal_notes"),
        frontmatter.get("warm_intro_path"),
        list(frontmatter.get("tags") or []),
        # recent_rounds / red_flags: frontmatter has strings, store as JSON string value
        _to_jsonb(frontmatter.get("recent_activity") or frontmatter.get("recent_rounds")),
        _to_jsonb(frontmatter.get("red_flags")),
        source_path,
    )
    return True


def _iter_contact_files(vault_root: Path):
    for sub in CONTACTS_SUBPATHS:
        folder = vault_root / sub
        if not folder.is_dir():
            logger.warning(f"skipping missing folder: {folder}")
            continue
        for md in sorted(folder.glob("*.md")):
            if md.name == "TEMPLATE.md":
                continue
            rel = md.relative_to(vault_root).as_posix()
            yield rel, md


async def sync_contacts_from_vault(vault_path: str | Path | None = None) -> IngestStats:
    """Walk the Obsidian vault and upsert every contact .md into Supabase.

    Vault path resolution order:
    1. Explicit argument
    2. DORMY_OBSIDIAN_VAULT_PATH env var (via settings.obsidian_vault_path)
    """
    resolved = Path(vault_path or settings.obsidian_vault_path or "")
    if not resolved.is_dir():
        raise FileNotFoundError(
            f"Vault path does not exist or is not a directory: {resolved!r}. "
            "Set DORMY_OBSIDIAN_VAULT_PATH in .env."
        )
    if not settings.database_url:
        raise RuntimeError("DORMY_DATABASE_URL not configured")

    logger.info(f"Vault: {resolved}")
    stats = IngestStats()

    conn = await asyncpg.connect(settings.database_url, statement_cache_size=0)
    try:
        for rel_path, md_path in _iter_contact_files(resolved):
            stats.scanned += 1
            frontmatter, _body = parse_markdown_file(md_path)
            if not frontmatter:
                logger.warning(f"[skip] {rel_path}: no frontmatter")
                stats.skipped += 1
                continue
            wrote = await upsert_contact(
                conn, source_path=rel_path, frontmatter=frontmatter
            )
            if wrote:
                stats.upserted += 1
                logger.debug(f"upserted {rel_path}  →  {frontmatter.get('name')}")
            else:
                stats.skipped += 1
    finally:
        await conn.close()

    logger.success(
        f"Contacts sync done: {stats.upserted} upserted, "
        f"{stats.skipped} skipped, {stats.scanned} total scanned."
    )
    return stats
