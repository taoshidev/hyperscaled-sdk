"""CLI commands for Vanta Network rules."""

from decimal import Decimal

from rich.console import Console
import typer

from hyperscaled.models.rules import Rule

app = typer.Typer(no_args_is_help=True)
console = Console()


def _render_rule(rule: Rule) -> None:
    applies_to = f" [{rule.applies_to}]" if rule.applies_to else ""
    console.print(f"- {rule.rule_id}: {rule.description}{applies_to} (limit={rule.limit})")


@app.command("list")
def list_rules(
    category: str | None = typer.Option(None, help="Filter by category"),
) -> None:
    """List all Vanta Network trading rules."""
    from hyperscaled import HyperscaledClient
    from hyperscaled.exceptions import HyperscaledError

    client = HyperscaledClient()
    client.open_sync()
    try:
        rules = client.rules.list_all()
        if category:
            rules = [rule for rule in rules if rule.category == category]  # type: ignore[assignment]
        if not rules:
            console.print("No rules found.")
            return
        for rule in rules:  # type: ignore[union-attr]
            _render_rule(rule)
    except HyperscaledError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from None
    finally:
        client.close_sync()


@app.command("check")
def check(
    pair: str,
    size: float,
    side: str = typer.Option("long", help="Trade side: long or short"),
    order_type: str = typer.Option("market", "--type", help="Order type: market or limit"),
    price: float | None = typer.Option(None, help="Limit price if applicable"),
) -> None:
    """Validate a hypothetical trade against rules."""
    from hyperscaled import HyperscaledClient
    from hyperscaled.exceptions import HyperscaledError, RuleViolationError

    client = HyperscaledClient()
    client.open_sync()
    try:
        result = client.rules.validate_trade(
            pair=pair,
            side=side,
            size=Decimal(str(size)),
            order_type=order_type,
            price=Decimal(str(price)) if price is not None else None,
        )
        console.print("Trade is valid.")
        if not result.valid:  # type: ignore[union-attr]
            console.print(result)
    except RuleViolationError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from None
    except HyperscaledError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from None
    finally:
        client.close_sync()
