"""CLI commands for orders."""

import json
from decimal import Decimal

import typer

from hyperscaled.cli._json_error import json_error
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
        if json_output:
            json_error(exc)
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


def _fmt_pnl(value: Decimal | None) -> str:
    if value is None:
        return "--"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:,.2f}"


@app.command("history")
def history(
    from_date: str | None = typer.Option(None, "--from", help="Start date (YYYY-MM-DD)"),
    to_date: str | None = typer.Option(None, "--to", help="End date (YYYY-MM-DD)"),
    pair: str | None = typer.Option(None, help="Filter by trading pair"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Show filled order history."""
    from datetime import datetime, timezone

    parsed_from = None
    parsed_to = None
    if from_date is not None:
        try:
            parsed_from = datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            typer.echo(f"Error: invalid --from date '{from_date}', expected YYYY-MM-DD", err=True)
            raise typer.Exit(1) from None
    if to_date is not None:
        try:
            parsed_to = datetime.strptime(to_date, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59, tzinfo=timezone.utc,
            )
        except ValueError:
            typer.echo(f"Error: invalid --to date '{to_date}', expected YYYY-MM-DD", err=True)
            raise typer.Exit(1) from None

    try:
        client = HyperscaledClient()
        orders = client.portfolio.order_history(
            from_date=parsed_from, to_date=parsed_to, pair=pair,
        )
    except HyperscaledError as exc:
        if json_output:
            json_error(exc)
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from None

    if json_output:
        data = [o.model_dump(mode="json") for o in orders]
        typer.echo(json.dumps(data, indent=2, default=str))
        return

    if not orders:
        typer.echo("No filled orders found.")
        return

    header = (
        f"{'Pair':<12} {'Side':<6} {'Size':>14} {'Fill Price':>14} "
        f"{'Filled':<20}"
    )
    typer.echo(header)
    typer.echo("─" * len(header))
    for o in orders:
        typer.echo(
            f"{o.pair:<12} {o.side:<6} {_fmt(o.size):>14} "
            f"{_fmt(o.fill_price):>14} "
            f"{o.created_at.strftime('%Y-%m-%d %H:%M'):<20}"
        )
