"""Knowledge ingest — Obsidian vault → Supabase contacts + gtm_advisors tables.

Two independent passes, one per vault folder, each writing to its own table:

    Network/Investors/*.md  →  contacts       (role: vc | angel)
    Network/GTM/*.md        →  gtm_advisors   (role: gtm-advisor | operator | founder-peer)

Both use `source_path` (the .md path relative to the vault root, e.g.
`Network/GTM/emma-yu.md`) as the natural dedup key for idempotent upsert.

The split lives here, not at the CLI layer, so direct callers
(`dormy.cli.commands.knowledge_sync`, future tests, future MCP `sync_now`
tool) all share the same routing logic.

Knowledge-chunks RAG ingest (Fundraising/, GTM/, Playbooks/) is in
`dormy.knowledge.knowledge_ingest`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import asyncpg
from loguru import logger

from dormy.config import settings
from dormy.knowledge.obsidian import parse_markdown_file


INVESTORS_SUBPATH = "Network/Investors"
GTM_SUBPATH = "Network/GTM"


@dataclass(slots=True)
class IngestStats:
    scanned: int = 0
    upserted: int = 0
    skipped: int = 0


def _to_jsonb(value) -> str | None:
    """Serialize to a JSON string for asyncpg jsonb binding. Empty → None."""
    if value is None or value == "":
        return None
    return json.dumps(value)


def _iter_md_files(vault_root: Path, subpath: str):
    """Yield (relative_posix_path, absolute_path) for every non-template .md under subpath."""
    folder = vault_root / subpath
    if not folder.is_dir():
        logger.warning(f"skipping missing folder: {folder}")
        return
    for md in sorted(folder.glob("*.md")):
        if md.name == "TEMPLATE.md":
            continue
        rel = md.relative_to(vault_root).as_posix()
        yield rel, md


# ============================================================================
# Investors → contacts table
# ============================================================================


def _infer_investor_role(frontmatter_role: str | None) -> str:
    """Default vc; frontmatter overrides (e.g. 'angel')."""
    return frontmatter_role or "vc"


async def upsert_contact(
    conn: asyncpg.Connection,
    *,
    source_path: str,
    frontmatter: dict,
) -> bool:
    """Upsert one investor row into `contacts`. Returns True if a row was written."""
    name = frontmatter.get("name")
    if not name:
        logger.warning(f"[skip] {source_path}: missing 'name' in frontmatter")
        return False

    role = _infer_investor_role(frontmatter.get("role"))
    tier = frontmatter.get("tier", "inner")  # Network/** is Inner Circle by convention

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
        # frontmatter has 'recent_activity' (string); legacy column name is recent_rounds
        _to_jsonb(frontmatter.get("recent_activity") or frontmatter.get("recent_rounds")),
        _to_jsonb(frontmatter.get("red_flags")),
        source_path,
    )
    return True


# ============================================================================
# GTM → gtm_advisors table
# ============================================================================


def _infer_gtm_role(frontmatter_role: str | None) -> str:
    """Default gtm-advisor; frontmatter overrides (operator | founder-peer)."""
    return frontmatter_role or "gtm-advisor"


async def upsert_gtm_advisor(
    conn: asyncpg.Connection,
    *,
    source_path: str,
    frontmatter: dict,
) -> bool:
    """Upsert one GTM row into `gtm_advisors`. Returns True if a row was written."""
    name = frontmatter.get("name")
    if not name:
        logger.warning(f"[skip] {source_path}: missing 'name' in frontmatter")
        return False

    role = _infer_gtm_role(frontmatter.get("role"))
    tier = frontmatter.get("tier", "inner")

    await conn.execute(
        """
        INSERT INTO gtm_advisors (
            name, role, tier, firm, email, sectors,
            linkedin_url, twitter_url, personal_notes, warm_intro_path,
            recent_activity, red_flags, tags, source_path, updated_at
        )
        VALUES ($1, $2, $3, $4, $5, $6,
                $7, $8, $9, $10,
                $11::jsonb, $12::jsonb, $13, $14, now())
        ON CONFLICT (source_path) DO UPDATE SET
            name              = EXCLUDED.name,
            role              = EXCLUDED.role,
            tier              = EXCLUDED.tier,
            firm              = EXCLUDED.firm,
            email             = EXCLUDED.email,
            sectors           = EXCLUDED.sectors,
            linkedin_url      = EXCLUDED.linkedin_url,
            twitter_url       = EXCLUDED.twitter_url,
            personal_notes    = EXCLUDED.personal_notes,
            warm_intro_path   = EXCLUDED.warm_intro_path,
            recent_activity   = EXCLUDED.recent_activity,
            red_flags         = EXCLUDED.red_flags,
            tags              = EXCLUDED.tags,
            updated_at        = now()
        """,
        name,
        role,
        tier,
        frontmatter.get("firm"),
        frontmatter.get("email"),
        list(frontmatter.get("sectors") or []),
        frontmatter.get("linkedin_url"),
        frontmatter.get("twitter_url"),
        frontmatter.get("personal_notes"),
        frontmatter.get("warm_intro_path"),
        _to_jsonb(frontmatter.get("recent_activity")),
        _to_jsonb(frontmatter.get("red_flags")),
        list(frontmatter.get("tags") or []),
        source_path,
    )
    return True


# ============================================================================
# Sync drivers — one per vault folder
# ============================================================================


async def _resolve_vault(vault_path: str | Path | None) -> Path:
    resolved = Path(vault_path or settings.obsidian_vault_path or "")
    if not resolved.is_dir():
        raise FileNotFoundError(
            f"Vault path does not exist or is not a directory: {resolved!r}. "
            "Set DORMY_OBSIDIAN_VAULT_PATH in .env."
        )
    if not settings.database_url:
        raise RuntimeError("DORMY_DATABASE_URL not configured")
    return resolved


async def sync_contacts_from_vault(vault_path: str | Path | None = None) -> IngestStats:
    """Walk Network/Investors/*.md and upsert into contacts table.

    Vault path resolution order:
      1. Explicit argument
      2. DORMY_OBSIDIAN_VAULT_PATH (via settings.obsidian_vault_path)
    """
    resolved = await _resolve_vault(vault_path)
    logger.info(f"Vault: {resolved}  (Investors -> contacts)")
    stats = IngestStats()

    conn = await asyncpg.connect(settings.database_url, statement_cache_size=0)
    try:
        for rel_path, md_path in _iter_md_files(resolved, INVESTORS_SUBPATH):
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
                logger.debug(f"upserted {rel_path}  ->  {frontmatter.get('name')}")
            else:
                stats.skipped += 1
    finally:
        await conn.close()

    logger.success(
        f"Contacts sync done: {stats.upserted} upserted, "
        f"{stats.skipped} skipped, {stats.scanned} total scanned."
    )
    return stats


async def sync_gtm_from_vault(vault_path: str | Path | None = None) -> IngestStats:
    """Walk Network/GTM/*.md and upsert into gtm_advisors table."""
    resolved = await _resolve_vault(vault_path)
    logger.info(f"Vault: {resolved}  (GTM -> gtm_advisors)")
    stats = IngestStats()

    conn = await asyncpg.connect(settings.database_url, statement_cache_size=0)
    try:
        for rel_path, md_path in _iter_md_files(resolved, GTM_SUBPATH):
            stats.scanned += 1
            frontmatter, _body = parse_markdown_file(md_path)
            if not frontmatter:
                logger.warning(f"[skip] {rel_path}: no frontmatter")
                stats.skipped += 1
                continue
            wrote = await upsert_gtm_advisor(
                conn, source_path=rel_path, frontmatter=frontmatter
            )
            if wrote:
                stats.upserted += 1
                logger.debug(f"upserted {rel_path}  ->  {frontmatter.get('name')}")
            else:
                stats.skipped += 1
    finally:
        await conn.close()

    logger.success(
        f"GTM sync done: {stats.upserted} upserted, "
        f"{stats.skipped} skipped, {stats.scanned} total scanned."
    )
    return stats
