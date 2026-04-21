"""Dormy CLI — typer app.

Run `dormy --help` for available commands.
Week 1: version + init stubs only. Real implementations land in Week 2-5.
"""

from typing import Optional

import typer

from dormy import __version__

app = typer.Typer(
    name="dormy",
    help="Fundraising copilot for founders — MCP + CLI + proactive watchers.",
    no_args_is_help=True,
    add_completion=False,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"dormy {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        "-v",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """Dormy CLI — interact with your Fundraising copilot."""


# ---------------------------------------------------------------------------
# Placeholder commands (Week 1 scaffolding; real implementations in Week 2-5)
# ---------------------------------------------------------------------------


@app.command()
def init() -> None:
    """Initialize local Dormy config under ~/.dormy/ (Week 2)."""
    typer.echo("[TODO Week 2] `dormy init` — create ~/.dormy/ and config.json")


@app.command()
def scan(url: str) -> None:
    """Scan a product URL and return structured profile (Week 3)."""
    typer.echo(f"[TODO Week 3] `dormy scan {url}` — Playwright + vision pipeline")


@app.command()
def match() -> None:
    """Find matching investors for current founder profile (Week 3)."""
    typer.echo("[TODO Week 3] `dormy match` — Inner Circle × Active VC playbook")


@app.command()
def watch(query: str) -> None:
    """Register a daily VC watcher (Week 4)."""
    typer.echo(f"[TODO Week 4] `dormy watch {query}` — Email/Telegram push")


@app.command()
def balance() -> None:
    """Show credits balance (Week 4)."""
    typer.echo("[TODO Week 4] `dormy balance` — Stripe + credits_ledger query")


@app.command()
def topup(amount: int = 20) -> None:
    """Top up credits via Stripe Checkout (Week 4)."""
    typer.echo(f"[TODO Week 4] `dormy topup ${amount}` — Stripe Checkout URL")


# ---------------------------------------------------------------------------
# Week 2 — MCP server
# ---------------------------------------------------------------------------


@app.command("mcp-serve")
def mcp_serve() -> None:
    """Run the Dormy MCP server over stdio (for local Claude Code / Cursor)."""
    from dormy.mcp.server import main as mcp_main

    mcp_main()


# ---------------------------------------------------------------------------
# Week 2 — knowledge & contacts ingest
# ---------------------------------------------------------------------------

knowledge_app = typer.Typer(help="Ingest Obsidian vault content into Supabase.")
contacts_app = typer.Typer(help="Manage Inner Circle contacts (import / list).")
app.add_typer(knowledge_app, name="knowledge")
app.add_typer(contacts_app, name="contacts")


@knowledge_app.command("sync")
def knowledge_sync(
    vault: Optional[str] = typer.Option(
        None,
        "--vault",
        help="Path to Dormy/ folder in the Obsidian vault. Defaults to DORMY_OBSIDIAN_VAULT_PATH.",
    ),
    contacts_only: bool = typer.Option(
        False, "--contacts-only", help="Skip the knowledge_chunks ingest"
    ),
    knowledge_only: bool = typer.Option(
        False, "--knowledge-only", help="Skip the contacts ingest"
    ),
    max_files: Optional[int] = typer.Option(
        None, "--max-files", help="Cap on knowledge files to process (useful for first runs)"
    ),
) -> None:
    """Sync Obsidian vault into Supabase.

    By default this runs both passes:
    1. Network/{Investors,Advisors}/*.md  →  contacts table
    2. Fundraising/ + GTM/ + Playbooks/   →  knowledge_chunks (chunked + embedded)
    """
    import asyncio

    async def _run() -> None:
        if not knowledge_only:
            from dormy.knowledge.ingest import sync_contacts_from_vault

            stats = await sync_contacts_from_vault(vault)
            typer.secho(
                f"✓ contacts: {stats.upserted} upserted · {stats.skipped} skipped "
                f"· {stats.scanned} scanned",
                fg=typer.colors.GREEN,
                bold=True,
            )

        if not contacts_only:
            from dormy.knowledge.knowledge_ingest import sync_knowledge_from_vault

            stats = await sync_knowledge_from_vault(vault, max_files=max_files)
            typer.secho(
                f"✓ knowledge: {stats.files_scanned} files → "
                f"{stats.chunks_written} chunks ({stats.files_skipped} skipped, "
                f"{len(stats.errors)} errors)",
                fg=typer.colors.GREEN,
                bold=True,
            )

    asyncio.run(_run())


@contacts_app.command("import")
def contacts_import(
    csv_path: str = typer.Argument(..., help="CSV file with header row"),
    tier: str = typer.Option(
        "inner",
        "--tier",
        help="Override tier for all rows (inner | public | discovered)",
    ),
) -> None:
    """Bulk-import contacts from a CSV. Columns: name,role,firm,email,sectors,stages,linkedin_url,twitter_url,personal_notes,warm_intro_path,tags,recent_activity,red_flags.

    `sectors`/`stages`/`tags` accept semicolon-separated values (e.g. 'ai-infra;dev-tools').
    """
    import asyncio
    import csv

    import asyncpg

    from dormy.config import settings
    from dormy.knowledge.ingest import upsert_contact

    def _split(raw: str | None) -> list[str]:
        if not raw:
            return []
        return [s.strip() for s in raw.split(";") if s.strip()]

    async def _run() -> None:
        if not settings.database_url:
            typer.secho("DORMY_DATABASE_URL not set", fg=typer.colors.RED)
            raise typer.Exit(1)

        with open(csv_path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        if not rows:
            typer.echo("No rows in CSV")
            return

        conn = await asyncpg.connect(settings.database_url, statement_cache_size=0)
        upserted = 0
        try:
            for i, row in enumerate(rows, 1):
                fm = {
                    "name": row.get("name"),
                    "role": row.get("role"),
                    "tier": row.get("tier") or tier,
                    "firm": row.get("firm"),
                    "email": row.get("email"),
                    "sectors": _split(row.get("sectors")),
                    "stages": _split(row.get("stages")),
                    "linkedin_url": row.get("linkedin_url"),
                    "twitter_url": row.get("twitter_url"),
                    "personal_notes": row.get("personal_notes"),
                    "warm_intro_path": row.get("warm_intro_path"),
                    "tags": _split(row.get("tags")),
                    "recent_activity": row.get("recent_activity"),
                    "red_flags": row.get("red_flags"),
                }
                source_path = f"csv-import/{csv_path}#row={i}"
                wrote = await upsert_contact(
                    conn, source_path=source_path, frontmatter=fm
                )
                if wrote:
                    upserted += 1
        finally:
            await conn.close()

        typer.secho(f"✓ {upserted} contacts upserted from {csv_path}", fg=typer.colors.GREEN)

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Week 1 diagnostics
# ---------------------------------------------------------------------------


@app.command("db-ping")
def db_ping() -> None:
    """Verify Supabase Postgres connectivity and schema."""
    import asyncio

    from dormy.db import close_pool, ping

    async def _run() -> None:
        try:
            result = await ping()
        finally:
            await close_pool()

        if result["ok"]:
            typer.secho("✓ Connected", fg=typer.colors.GREEN, bold=True)
        else:
            typer.secho("✗ Connection responded but SELECT 1 failed", fg=typer.colors.RED)
            raise typer.Exit(1)

        typer.echo(f"  Postgres: {result['postgres_version']}")
        typer.echo(f"  Tables in public schema ({result['table_count']}):")
        for name in result["tables"]:
            typer.echo(f"    - {name}")

    asyncio.run(_run())


if __name__ == "__main__":
    app()
