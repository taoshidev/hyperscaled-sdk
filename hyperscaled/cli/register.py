"""CLI commands for funded account registration."""

from __future__ import annotations

from typing import cast

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from hyperscaled import HyperscaledClient
from hyperscaled.exceptions import (
    HyperscaledError,
    InsufficientBalanceError,
    InvalidMinerError,
    PaymentError,
    RegistrationError,
    UnsupportedAccountSizeError,
)
from hyperscaled.models import EntityMiner, RegistrationStatus

app = typer.Typer(no_args_is_help=True, invoke_without_command=True)
console = Console()


def _wallet_error(address: str) -> str:
    return f"Invalid wallet address: {address!r} — expected format 0x followed by 40 hex chars"


def _resolve_wallet_or_exit(client: HyperscaledClient, wallet_address: str | None) -> str:
    resolved = wallet_address if wallet_address is not None else client.config.wallet.hl_address
    if not resolved:
        console.print(
            "[red]Error:[/red] No Hyperliquid wallet configured. "
            "Run `hyperscaled account setup <wallet>` or pass `--hl-wallet`."
        )
        raise typer.Exit(code=1) from None
    if not client.account.validate_wallet(resolved):
        console.print(f"[red]Error:[/red] {_wallet_error(resolved)}")
        raise typer.Exit(code=1) from None
    return resolved


def _render_miner_pricing(miner: EntityMiner) -> Panel:
    """Build a Rich panel showing the miner's pricing tiers."""
    table = Table(show_header=True, header_style="bold")
    table.add_column("Account Size", style="cyan")
    table.add_column("Cost")
    table.add_column("Profit Split")

    for tier in miner.pricing_tiers:
        table.add_row(
            f"${tier.account_size:,}",
            f"${tier.cost}",
            f"{tier.profit_split.trader_pct}/{tier.profit_split.miner_pct}",
        )

    return Panel(table, title=f"{miner.name} — Pricing", border_style="cyan")


def _render_result(result: RegistrationStatus) -> Panel:
    """Build a Rich panel showing the purchase result."""
    lines = [
        f"[bold]Status:[/bold]          {result.status}",
        f"[bold]Registration ID:[/bold] {result.registration_id}",
        f"[bold]Account Size:[/bold]    ${result.account_size:,}",
    ]
    if result.tx_hash:
        lines.append(f"[bold]Tx Hash:[/bold]         {result.tx_hash}")
    if result.message:
        lines.append(f"[bold]Message:[/bold]         {result.message}")
    if result.estimated_time:
        lines.append(f"[bold]Estimated Time:[/bold] {result.estimated_time}")

    style = "green" if result.status == "registered" else "yellow"
    return Panel("\n".join(lines), title="Registration Result", border_style=style)


def _run_purchase(
    miner_slug: str,
    size: int,
    hl_wallet: str | None,
    payout_wallet: str | None,
    email: str | None,
) -> None:
    client = HyperscaledClient()

    # Resolve HL wallet
    resolved_hl = _resolve_wallet_or_exit(client, hl_wallet)

    # Resolve payout wallet (default to HL wallet)
    resolved_payout = payout_wallet or client.config.wallet.payout_address or resolved_hl

    # Fetch and display miner pricing
    try:
        miner = cast(EntityMiner, client.miners.get(miner_slug))
    except HyperscaledError as exc:
        console.print(f"[red]Error:[/red] {exc.message}")
        raise typer.Exit(code=1) from None

    console.print(_render_miner_pricing(miner))

    # Confirm purchase
    if not typer.confirm("Proceed with purchase?"):
        raise typer.Abort()

    # Execute purchase
    try:
        result = cast(
            RegistrationStatus,
            client.register.purchase(
                miner_slug,
                size,
                resolved_hl,
                resolved_payout,
                email=email,
            ),
        )
    except InsufficientBalanceError as exc:
        console.print(f"[red]Error:[/red] {exc.message}")
        raise typer.Exit(code=1) from None
    except PaymentError as exc:
        console.print(f"[red]Payment Error:[/red] {exc.message}")
        raise typer.Exit(code=1) from None
    except RegistrationError as exc:
        console.print(f"[red]Registration Error:[/red] {exc.message}")
        raise typer.Exit(code=1) from None
    except InvalidMinerError as exc:
        console.print(f"[red]Error:[/red] {exc.message}")
        raise typer.Exit(code=1) from None
    except UnsupportedAccountSizeError as exc:
        console.print(f"[red]Error:[/red] {exc.message}")
        raise typer.Exit(code=1) from None

    console.print(_render_result(result))


@app.callback()
def register(
    ctx: typer.Context,
    miner: str | None = typer.Option(None, "--miner", help="Entity miner slug"),
    size: int | None = typer.Option(None, "--size", help="Funded account size"),
    hl_wallet: str | None = typer.Option(None, "--hl-wallet", help="Hyperliquid wallet address"),
    payout_wallet: str | None = typer.Option(
        None, "--payout-wallet", help="Payout wallet address (defaults to HL wallet)"
    ),
    email: str | None = typer.Option(None, "--email", help="Email for registration confirmation"),
) -> None:
    """Purchase and connect a funded account."""
    if ctx.invoked_subcommand is not None:
        return
    if miner is None or size is None:
        raise typer.Exit()
    _run_purchase(
        miner_slug=miner,
        size=size,
        hl_wallet=hl_wallet,
        payout_wallet=payout_wallet,
        email=email,
    )


@app.command("purchase")
def purchase(
    miner: str = typer.Option(..., help="Entity miner slug"),
    size: int = typer.Option(..., help="Funded account size"),
    hl_wallet: str | None = typer.Option(None, "--hl-wallet", help="Hyperliquid wallet address"),
    payout_wallet: str | None = typer.Option(
        None, "--payout-wallet", help="Payout wallet address (defaults to HL wallet)"
    ),
    email: str | None = typer.Option(None, "--email", help="Email for registration confirmation"),
) -> None:
    """Purchase a funded trading account via x402 payment."""
    _run_purchase(
        miner_slug=miner,
        size=size,
        hl_wallet=hl_wallet,
        payout_wallet=payout_wallet,
        email=email,
    )


@app.command("status")
def status() -> None:
    """Check registration status."""
    typer.echo("Not yet implemented — target: Sprint 05 (SDK-008)")
