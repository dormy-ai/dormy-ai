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
