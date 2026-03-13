"""CLI commands for Hyperliquid account setup and balance checking."""

from __future__ import annotations

import json
from typing import cast

import typer
from rich.console import Console

from hyperscaled import HyperscaledClient
from hyperscaled.exceptions import HyperscaledError
from hyperscaled.models.account import BalanceStatus

app = typer.Typer(no_args_is_help=True)
console = Console()


def _wallet_error(address: str) -> str:
    return f"Invalid wallet address: {address!r} — expected format 0x followed by 40 hex chars"


@app.command("setup")
def setup(wallet_address: str = typer.Argument(..., help="Hyperliquid wallet address")) -> None:
    """Validate and save the Hyperliquid wallet address."""
    client = HyperscaledClient()
    if not client.account.validate_wallet(wallet_address):
        console.print(f"[red]Error:[/red] {_wallet_error(wallet_address)}")
        raise typer.Exit(code=1) from None

    client.config.set_value("wallet.hl_address", wallet_address)
    client.config.save()
    console.print(f"[green]Set[/green] wallet.hl_address = {wallet_address}")


@app.command("check")
def check(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
    wallet: str | None = typer.Option(None, "--wallet", help="Override configured HL wallet"),
) -> None:
    """Check account balance and minimum requirements."""
    client = HyperscaledClient()
    try:
        status = cast(BalanceStatus, client.account.check_balance(wallet))
    except HyperscaledError as exc:
        console.print(f"[red]Error:[/red] {exc.message}")
        raise typer.Exit(code=1) from None

    if json_output:
        typer.echo(json.dumps(status.model_dump(mode="json"), indent=2))
        return

    _render_balance(status)


def _render_balance(status: BalanceStatus) -> None:
    """Pretty-print the balance check result."""
    balance_str = f"${status.balance:,.2f}"
    minimum_str = f"${status.minimum_required:,.2f}"

    verdict = "[green]PASS[/green]" if status.meets_minimum else "[red]FAIL[/red]"

    console.print(f"Balance:          {balance_str}")
    console.print(f"Minimum required: {minimum_str}")
    console.print(f"Status:           {verdict}")
