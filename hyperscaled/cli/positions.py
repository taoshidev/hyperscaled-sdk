"""CLI commands for positions."""

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


def _fmt_pnl(value: Decimal | None) -> str:
    if value is None:
        return "--"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:,.2f}"


@app.command("open")
def open_positions(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Show open positions."""
    try:
        client = HyperscaledClient()
        positions = client.portfolio.open_positions()
    except HyperscaledError as exc:
        if json_output:
            json_error(exc)
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from None

    if json_output:
        data = [p.model_dump(mode="json") for p in positions]
        typer.echo(json.dumps(data, indent=2, default=str))
        return

    if not positions:
        typer.echo("No open positions.")
        return

    header = f"{'Pair':<12} {'Side':<6} {'Size':>14} {'Value':>14} {'Entry':>14} {'Unrealized PnL':>16} {'Opened':<20}"
    typer.echo(header)
    typer.echo("─" * len(header))
    for p in positions:
        typer.echo(
            f"{p.symbol:<12} {p.side:<6} {_fmt(p.size):>14} {_fmt(p.position_value):>14} "
            f"{_fmt(p.entry_price):>14} {_fmt_pnl(p.unrealized_pnl):>16} "
            f"{p.open_time.strftime('%Y-%m-%d %H:%M'):<20}"
        )


@app.command("history")
def history(
    from_date: str | None = typer.Option(None, "--from", help="Start date (YYYY-MM-DD)"),
    to_date: str | None = typer.Option(None, "--to", help="End date (YYYY-MM-DD)"),
    pair: str | None = typer.Option(None, help="Filter by trading pair"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Show closed position history."""
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
            # End of day: set to 23:59:59 so the whole day is included.
            parsed_to = datetime.strptime(to_date, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59, tzinfo=timezone.utc,
            )
        except ValueError:
            typer.echo(f"Error: invalid --to date '{to_date}', expected YYYY-MM-DD", err=True)
            raise typer.Exit(1) from None

    try:
        client = HyperscaledClient()
        positions = client.portfolio.position_history(
            from_date=parsed_from, to_date=parsed_to, pair=pair,
        )
    except HyperscaledError as exc:
        if json_output:
            json_error(exc)
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from None

    if json_output:
        data = [p.model_dump(mode="json") for p in positions]
        typer.echo(json.dumps(data, indent=2, default=str))
        return

    if not positions:
        typer.echo("No closed positions found.")
        return

    header = (
        f"{'Pair':<12} {'Side':<6} {'Size':>14} {'Entry':>14} "
        f"{'Realized PnL':>14} {'Closed':<20}"
    )
    typer.echo(header)
    typer.echo("─" * len(header))
    for p in positions:
        typer.echo(
            f"{p.symbol:<12} {p.side:<6} {_fmt(p.size):>14} "
            f"{_fmt(p.entry_price):>14} {_fmt_pnl(p.realized_pnl):>14} "
            f"{p.close_time.strftime('%Y-%m-%d %H:%M'):<20}"
        )
