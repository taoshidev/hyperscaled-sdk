"""CLI commands for Hyperliquid account setup."""

from __future__ import annotations

import typer
from rich.console import Console

from hyperscaled import HyperscaledClient

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


@app.command("fund")
def fund(amount: float = typer.Option(..., help="USDC amount to fund")) -> None:
    """Fund your Hyperliquid account."""
    typer.echo(f"Not yet implemented — target: Sprint 05 (SDK-006) [amount={amount}]")


@app.command("check")
def check() -> None:
    """Check account balance and minimum requirements."""
    typer.echo("Not yet implemented — target: Sprint 05 (SDK-006)")


@app.command("status")
def status() -> None:
    """Show account status."""
    typer.echo("Not yet implemented — target: Sprint 05 (SDK-006)")
