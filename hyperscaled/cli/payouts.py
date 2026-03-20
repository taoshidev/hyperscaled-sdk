"""CLI commands for payout history and pending payouts."""

from __future__ import annotations

import json
from typing import cast

import typer
from rich.console import Console
from rich.table import Table

from hyperscaled.cli._json_error import json_error
from hyperscaled.exceptions import HyperscaledError
from hyperscaled.models.payout import Payout
from hyperscaled.sdk.client import HyperscaledClient

app = typer.Typer(no_args_is_help=True)
console = Console()


def _status_style(status: str) -> str:
    """Return a Rich-styled status string."""
    styles = {
        "completed": "[green]completed[/green]",
        "pending": "[yellow]pending[/yellow]",
        "processing": "[blue]processing[/blue]",
        "failed": "[red]failed[/red]",
    }
    return styles.get(status, status)


@app.command("history")
def history(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Show payout history."""
    client = HyperscaledClient()
    try:
        payouts = cast(list[Payout], client.payouts.history())
    except HyperscaledError as exc:
        if json_output:
            json_error(exc)
        console.print(f"[red]Error:[/red] {exc.message}")
        raise typer.Exit(code=1) from None

    if json_output:
        data = [p.model_dump(mode="json") for p in payouts]
        typer.echo(json.dumps(data, indent=2, default=str))
        return

    if not payouts:
        typer.echo("No payouts found.")
        return

    table = Table(title="Payout History")
    table.add_column("Date", style="cyan")
    table.add_column("Amount", justify="right")
    table.add_column("Token")
    table.add_column("Network")
    table.add_column("Tx Hash")
    table.add_column("Status")

    for p in payouts:
        table.add_row(
            p.date.strftime("%Y-%m-%d %H:%M"),
            f"{p.amount:,.2f}",
            p.token,
            p.network,
            (p.tx_hash or "--")[:16] + ("..." if p.tx_hash and len(p.tx_hash) > 16 else ""),
            _status_style(p.status),
        )

    console.print(table)


@app.command("pending")
def pending(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Show estimated next payout."""
    client = HyperscaledClient()
    try:
        payout = cast(Payout | None, client.payouts.pending())
    except HyperscaledError as exc:
        if json_output:
            json_error(exc)
        console.print(f"[red]Error:[/red] {exc.message}")
        raise typer.Exit(code=1) from None

    if payout is None:
        if json_output:
            typer.echo(json.dumps(None))
        else:
            typer.echo("No pending payout.")
        return

    if json_output:
        typer.echo(json.dumps(payout.model_dump(mode="json"), indent=2, default=str))
        return

    console.print(f"Status:   {_status_style(payout.status)}")
    console.print(f"Amount:   {payout.amount:,.2f} {payout.token}")
    console.print(f"Network:  {payout.network}")
    console.print(f"Date:     {payout.date.strftime('%Y-%m-%d %H:%M')}")
    if payout.tx_hash:
        console.print(f"Tx Hash:  {payout.tx_hash}")
