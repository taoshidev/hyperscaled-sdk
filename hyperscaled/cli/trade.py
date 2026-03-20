"""CLI commands for trade submission and cancellation."""

from __future__ import annotations

import json

import typer
from rich.console import Console
from rich.panel import Panel

from hyperscaled.cli._json_error import json_error
from hyperscaled.models.trading import Order

app = typer.Typer(no_args_is_help=True)
console = Console()


def _render_order(order: Order) -> None:
    """Print a human-readable summary of a submitted order."""
    lines = [
        f"[bold]Order ID:[/bold]       {order.hl_order_id}",
        f"[bold]Pair:[/bold]           {order.pair}",
        f"[bold]Side:[/bold]           {order.side}",
        f"[bold]Size:[/bold]           {order.size}",
        f"[bold]Type:[/bold]           {order.order_type}",
        f"[bold]Status:[/bold]         {order.status}",
    ]
    if order.fill_price is not None:
        lines.append(f"[bold]Fill Price:[/bold]     ${order.fill_price:,.2f}")
    lines.append(f"[bold]Scaling Ratio:[/bold] {order.scaling_ratio}")
    lines.append(f"[bold]Funded Size:[/bold]   ${order.funded_equivalent_size:,.2f}")
    if order.take_profit is not None:
        lines.append(f"[bold]Take Profit:[/bold]   ${order.take_profit:,.2f}")
    if order.stop_loss is not None:
        lines.append(f"[bold]Stop Loss:[/bold]     ${order.stop_loss:,.2f}")

    style = "green" if order.status == "filled" else "yellow"
    console.print(Panel("\n".join(lines), title="Order Submitted", border_style=style))


def _render_cancel_result(result: dict[str, object]) -> None:
    """Print a human-readable summary of a single cancellation attempt."""
    lines = [f"[bold]Order ID:[/bold]       {result['hl_order_id']}"]
    pair = result.get("pair")
    if pair:
        lines.append(f"[bold]Pair:[/bold]           {pair}")
    lines.append(f"[bold]Status:[/bold]         {result['status']}")
    lines.append(f"[bold]Message:[/bold]        {result['message']}")

    status = str(result["status"])
    if status == "cancelled":
        style = "green"
    elif status in {"not_found", "already_closed"}:
        style = "yellow"
    else:
        style = "red"
    console.print(Panel("\n".join(lines), title="Order Cancellation", border_style=style))


def _render_cancel_all_result(result: dict[str, object]) -> None:
    """Print a human-readable summary of a bulk cancellation attempt."""
    lines = [
        f"[bold]Status:[/bold]          {result['status']}",
        f"[bold]Message:[/bold]         {result['message']}",
        f"[bold]Open Orders:[/bold]     {result['total_open_orders']}",
        f"[bold]Cancelled:[/bold]       {result['cancelled_count']}",
        f"[bold]Failed:[/bold]          {result['failed_count']}",
    ]

    results = result.get("results", [])
    if isinstance(results, list) and results:
        lines.append("")
        lines.append("[bold]Per-order results:[/bold]")
        for entry in results:
            if isinstance(entry, dict):
                lines.append(
                    f"- {entry.get('hl_order_id')} {entry.get('pair', '')} -> "
                    f"{entry.get('status')}: {entry.get('message')}"
                )

    style = "green" if result["failed_count"] == 0 else "yellow"
    console.print(Panel("\n".join(lines), title="Cancel All Orders", border_style=style))


@app.command("submit")
def submit(
    pair: str = typer.Option(..., help="Trading pair (e.g. BTC-USDC)"),
    side: str = typer.Option(..., help="Trade side: long or short"),
    size: float = typer.Option(..., help="Position size in coin quantity (or USD with --usd)"),
    order_type: str = typer.Option("market", "--type", help="Order type: market or limit"),
    price: float | None = typer.Option(None, help="Limit price (required for limit orders)"),
    take_profit: float | None = typer.Option(None, "--tp", help="Take profit price"),
    stop_loss: float | None = typer.Option(None, "--sl", help="Stop loss price"),
    usd: bool = typer.Option(
        False,
        "--usd",
        help="Interpret --size as USD notional value instead of coin quantity.",
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Exit with code 1 on local rule violations without extra formatting.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Submit a trade on Hyperliquid."""
    from decimal import Decimal

    from hyperscaled import HyperscaledClient
    from hyperscaled.exceptions import HyperscaledError, RuleViolationError

    client = HyperscaledClient()
    client.open_sync()
    try:
        order = client.trade.submit(
            pair=pair,
            side=side,
            size=Decimal(str(size)),
            order_type=order_type,
            price=Decimal(str(price)) if price else None,
            take_profit=Decimal(str(take_profit)) if take_profit else None,
            stop_loss=Decimal(str(stop_loss)) if stop_loss else None,
            size_in_usd=usd,
        )
        if json_output:
            typer.echo(json.dumps(order.model_dump(mode="json"), indent=2, default=str))  # type: ignore[union-attr]
            return
        _render_order(order)  # type: ignore[arg-type]
    except (ValueError, HyperscaledError) as exc:
        if json_output:
            json_error(exc)
        if strict and isinstance(exc, RuleViolationError):
            console.print(str(exc))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from None
    finally:
        client.close_sync()


@app.command("cancel")
def cancel(
    order_id: str,
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Cancel an open order."""
    from hyperscaled import HyperscaledClient
    from hyperscaled.exceptions import HyperscaledError

    client = HyperscaledClient()
    client.open_sync()
    try:
        result = client.trade.cancel(order_id)
        if json_output:
            typer.echo(json.dumps(result, indent=2, default=str))  # type: ignore[arg-type]
            return
        _render_cancel_result(result)  # type: ignore[arg-type]
    except (ValueError, HyperscaledError) as exc:
        if json_output:
            json_error(exc)
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from None
    finally:
        client.close_sync()


@app.command("cancel-all")
def cancel_all(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Cancel all open orders."""
    from hyperscaled import HyperscaledClient
    from hyperscaled.exceptions import HyperscaledError

    client = HyperscaledClient()
    client.open_sync()
    try:
        result = client.trade.cancel_all()
        if json_output:
            typer.echo(json.dumps(result, indent=2, default=str))  # type: ignore[arg-type]
            return
        _render_cancel_all_result(result)  # type: ignore[arg-type]
    except (ValueError, HyperscaledError) as exc:
        if json_output:
            json_error(exc)
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from None
    finally:
        client.close_sync()
