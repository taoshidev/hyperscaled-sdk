"""CLI commands for trade submission. Target: Sprint 06."""

import typer

app = typer.Typer(no_args_is_help=True)


@app.command("submit")
def submit(
    pair: str = typer.Option(..., help="Trading pair (e.g. BTC-USDC)"),
    side: str = typer.Option(..., help="Trade side: long or short"),
    size: float = typer.Option(..., help="Position size"),
    order_type: str = typer.Option("market", "--type", help="Order type: market or limit"),
) -> None:
    """Submit a trade on Hyperliquid."""
    typer.echo(
        f"Not yet implemented — target: Sprint 06 (SDK-010) "
        f"[pair={pair}, side={side}, size={size}, type={order_type}]"
    )


@app.command("cancel")
def cancel(order_id: str) -> None:
    """Cancel an open order."""
    typer.echo(f"Not yet implemented — target: Sprint 06 (SDK-010) [order_id={order_id}]")


@app.command("cancel-all")
def cancel_all() -> None:
    """Cancel all open orders."""
    typer.echo("Not yet implemented — target: Sprint 06 (SDK-010)")
