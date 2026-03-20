"""CLI commands for account info and payouts."""

from __future__ import annotations

import json
from typing import cast

import typer
from rich.console import Console
from rich.table import Table

from hyperscaled.cli._json_error import json_error
from hyperscaled.models.account import AccountInfo, LeverageLimits

app = typer.Typer(no_args_is_help=True)
console = Console()


@app.command("account")
def account_info(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Show full account information."""
    from hyperscaled import HyperscaledClient
    from hyperscaled.exceptions import HyperscaledError

    client = HyperscaledClient()
    client.open_sync()
    try:
        info = cast(AccountInfo, client.account.info())

        if json_output:
            typer.echo(json.dumps(info.model_dump(mode="json"), indent=2))
            return

        _render_account_info(info)
    except HyperscaledError as exc:
        if json_output:
            json_error(exc)
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from None
    finally:
        client.close_sync()


def _render_account_info(info: AccountInfo) -> None:
    """Pretty-print the account info."""
    status_color = {
        "active": "green",
        "suspended": "yellow",
        "breached": "red",
        "pending_kyc": "yellow",
    }.get(info.status, "white")

    console.print(f"Status:              [{status_color}]{info.status}[/{status_color}]")
    console.print(f"Funded Account Size: ${info.funded_account_size:,}")
    console.print(f"HL Wallet:           {info.hl_wallet_address}")
    console.print(f"Payout Wallet:       {info.payout_wallet_address or 'not set'}")
    console.print(f"Entity Miner:        {info.entity_miner or 'unknown'}")
    console.print(f"Current Drawdown:    {info.current_drawdown}%")
    console.print(f"Max Drawdown Limit:  {info.max_drawdown_limit}%")
    console.print(f"HL Balance:          ${info.hl_balance:,.2f}")
    console.print(f"Funded Balance:      ${info.funded_balance:,.2f}")
    console.print(f"KYC Status:          {info.kyc_status}")
    console.print(f"Account Leverage:    {info.leverage_limits.account_level}x")


@app.command("limits")
def limits(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Show account leverage and exposure limits."""
    from hyperscaled import HyperscaledClient
    from hyperscaled.exceptions import HyperscaledError

    client = HyperscaledClient()
    client.open_sync()
    try:
        lev_limits = cast(LeverageLimits, client.account.limits())

        if json_output:
            typer.echo(json.dumps(lev_limits.model_dump(mode="json"), indent=2))
            return

        _render_limits(lev_limits)
    except HyperscaledError as exc:
        if json_output:
            json_error(exc)
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from None
    finally:
        client.close_sync()


def _render_limits(lev_limits: LeverageLimits) -> None:
    """Pretty-print leverage limits as a table."""
    console.print(f"Account-level max leverage: {lev_limits.account_level}x\n")

    table = Table(title="Per-Pair Leverage Limits")
    table.add_column("Pair", style="cyan")
    table.add_column("Max Leverage", justify="right")

    for pair, max_lev in sorted(lev_limits.position_level.items()):
        table.add_row(pair, f"{max_lev}x")

    console.print(table)


@app.command("payouts")
def payouts() -> None:
    """Show payout history (use `hyperscaled payouts` for full commands)."""
    typer.echo("Use `hyperscaled payouts history` or `hyperscaled payouts pending`.")
