"""CLI commands for funded account registration."""

from __future__ import annotations

import typer
from rich.console import Console

from hyperscaled import HyperscaledClient

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


def _run_purchase_preflight(miner: str, size: int, hl_wallet: str | None) -> None:
    client = HyperscaledClient()
    resolved_wallet = _resolve_wallet_or_exit(client, hl_wallet)
    typer.echo(
        "Not yet implemented — target: Sprint 05 (SDK-008) "
        f"[miner={miner}, size={size}, hl_wallet={resolved_wallet}]"
    )


@app.callback()
def register(
    ctx: typer.Context,
    miner: str | None = typer.Option(None, "--miner", help="Entity miner slug"),
    size: int | None = typer.Option(None, "--size", help="Funded account size"),
    hl_wallet: str | None = typer.Option(None, "--hl-wallet", help="Hyperliquid wallet address"),
) -> None:
    """Purchase and connect a funded account."""
    if ctx.invoked_subcommand is not None:
        return
    if miner is None or size is None:
        raise typer.Exit()
    _run_purchase_preflight(miner=miner, size=size, hl_wallet=hl_wallet)


@app.command("purchase")
def purchase(
    miner: str = typer.Option(..., help="Entity miner slug"),
    size: int = typer.Option(..., help="Funded account size"),
    hl_wallet: str | None = typer.Option(None, "--hl-wallet", help="Hyperliquid wallet address"),
) -> None:
    """Validate registration inputs before purchase/submit."""
    _run_purchase_preflight(miner=miner, size=size, hl_wallet=hl_wallet)


@app.command("status")
def status() -> None:
    """Check registration status."""
    typer.echo("Not yet implemented — target: Sprint 05 (SDK-008)")
