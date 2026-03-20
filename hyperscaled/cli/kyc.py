"""CLI commands for SumSub KYC identity verification."""

from __future__ import annotations

import json
import webbrowser
from typing import cast

import typer
from rich.console import Console

from hyperscaled.exceptions import HyperscaledError
from hyperscaled.models.kyc import KycInfo, KycTokenResponse
from hyperscaled.sdk.client import HyperscaledClient

app = typer.Typer(no_args_is_help=True)
console = Console()


def _status_style(kyc_status: str) -> str:
    """Return a Rich-styled KYC status string."""
    styles = {
        "none": "[dim]none[/dim]",
        "pending": "[yellow]pending[/yellow]",
        "approved": "[green]approved[/green]",
        "rejected": "[red]rejected[/red]",
    }
    return styles.get(kyc_status, kyc_status)


def _dashboard_url(client: HyperscaledClient) -> str:
    """Derive the browser dashboard URL from the configured API base URL."""
    base = client.config.api.hyperscaled_base_url
    return base.rstrip("/").removesuffix("/api") + "/dashboard"


@app.command("status")
def status(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Check KYC verification status."""
    client = HyperscaledClient()
    try:
        info = cast(KycInfo, client.kyc.status())
    except HyperscaledError as exc:
        console.print(f"[red]Error:[/red] {exc.message}")
        raise typer.Exit(code=1) from None

    if json_output:
        typer.echo(json.dumps(info.model_dump(mode="json"), indent=2, default=str))
        return

    console.print(f"Wallet:     {info.wallet}")
    console.print(f"KYC Status: {_status_style(info.kyc_status)}")
    console.print(f"Verified:   {'Yes' if info.verified else 'No'}")
    if info.verified_at:
        console.print(f"Verified At: {info.verified_at.strftime('%Y-%m-%d %H:%M UTC')}")


@app.command("start")
def start(
    no_browser: bool = typer.Option(False, "--no-browser", help="Don't open browser"),
) -> None:
    """Start the KYC verification flow via SumSub."""
    client = HyperscaledClient()

    # Check current status first — skip if already approved
    try:
        info = cast(KycInfo, client.kyc.status())
    except HyperscaledError as exc:
        console.print(f"[red]Error:[/red] {exc.message}")
        raise typer.Exit(code=1) from None

    if info.kyc_status == "approved":
        console.print("[green]KYC already approved.[/green] No further action needed.")
        return

    # Create applicant / get token
    try:
        cast(KycTokenResponse, client.kyc.start())
    except HyperscaledError as exc:
        console.print(f"[red]Error:[/red] {exc.message}")
        raise typer.Exit(code=1) from None

    dashboard = _dashboard_url(client)

    if not no_browser:
        webbrowser.open(dashboard)

    console.print("[bold]KYC verification started.[/bold]")
    console.print(f"Complete identity verification at: {dashboard}")
    console.print("Once verified, your status will update automatically.")
