"""CLI commands for orders."""

import json
from decimal import Decimal

import typer

from hyperscaled.exceptions import HyperscaledError
from hyperscaled.sdk.client import HyperscaledClient

app = typer.Typer(no_args_is_help=True)


def _fmt(value: Decimal | None) -> str:
    if value is None:
        return "--"
    return f"{value:,.4f}"


@app.command("open")
def open_orders(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Show open orders."""
    try:
        client = HyperscaledClient()
        orders = client.portfolio.open_orders()
    except HyperscaledError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from None

    if json_output:
        data = [o.model_dump(mode="json") for o in orders]
        typer.echo(json.dumps(data, indent=2, default=str))
        return

    if not orders:
        typer.echo("No open orders.")
        return

    header = f"{'Pair':<12} {'Side':<6} {'Type':<8} {'Limit Price':>14} {'Size':>14} {'Funded Size':>14} {'Created':<20}"
    typer.echo(header)
    typer.echo("─" * len(header))
    for o in orders:
        typer.echo(
            f"{o.pair:<12} {o.side:<6} {o.order_type:<8} {_fmt(o.limit_price):>14} "
            f"{_fmt(o.size):>14} {_fmt(o.funded_equivalent_size):>14} "
            f"{o.created_at.strftime('%Y-%m-%d %H:%M'):<20}"
        )


@app.command("history")
def history(
    from_date: str | None = typer.Option(None, "--from", help="Start date"),
    to_date: str | None = typer.Option(None, "--to", help="End date"),
    pair: str | None = typer.Option(None, help="Filter by trading pair"),
) -> None:
    """Show order history."""
    typer.echo(
        f"Not yet implemented — target: future sprint "
        f"[from={from_date}, to={to_date}, pair={pair}]"
    )
