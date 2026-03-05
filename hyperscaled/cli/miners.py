"""CLI commands for entity miner discovery."""

from __future__ import annotations

import json
from typing import cast

import typer
from rich.console import Console
from rich.table import Table

from hyperscaled import HyperscaledClient
from hyperscaled.exceptions import HyperscaledError
from hyperscaled.models import EntityMiner, PricingTier

app = typer.Typer(no_args_is_help=True)
console = Console()


def _profit_split_label(tier: PricingTier) -> str:
    return f"{tier.profit_split.trader_pct}/{tier.profit_split.miner_pct}"


def _profit_split_summary(miner: EntityMiner) -> str:
    labels = {_profit_split_label(tier) for tier in miner.pricing_tiers}
    if not labels:
        return "—"
    if len(labels) == 1:
        return labels.pop()
    return "Varies by tier"


def _render_list_table(miners: list[EntityMiner]) -> None:
    table = Table(title="Entity Miners")
    table.add_column("Miner", style="cyan", no_wrap=True)
    table.add_column("Profit Split")
    table.add_column("Payout Cadence")
    table.add_column("Account Sizes")

    for miner in miners:
        sizes = ", ".join(f"${size // 1000}K" for size in miner.available_account_sizes)
        table.add_row(miner.slug, _profit_split_summary(miner), miner.payout_cadence.title(), sizes)

    console.print(table)


def _render_info(miner: EntityMiner) -> None:
    console.print(f"Name:              {miner.name}")
    console.print(f"Slug:              {miner.slug}")
    console.print(f"Payout Cadence:    {miner.payout_cadence.title()}")
    console.print(f"Profit Split:      {_profit_split_summary(miner)}")
    if miner.brand_color:
        console.print(f"Brand Color:       {miner.brand_color}")
    console.print("")

    pricing = Table(title="Pricing")
    pricing.add_column("Account Size", style="cyan")
    pricing.add_column("Cost")
    pricing.add_column("Profit Split")
    for tier in miner.pricing_tiers:
        pricing.add_row(
            f"${tier.account_size:,}",
            f"${tier.cost}",
            _profit_split_label(tier),
        )
    console.print(pricing)


def _render_compare(miners: list[EntityMiner]) -> None:
    _render_list_table(miners)


def _print_json(data: object) -> None:
    typer.echo(json.dumps(data, indent=2))


@app.command("list")
def list_miners(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """List all entity miners on Hyperscaled."""
    try:
        miners = cast(list[EntityMiner], HyperscaledClient().miners.list_all())
    except HyperscaledError as exc:
        console.print(f"[red]Error:[/red] {exc.message}")
        raise typer.Exit(code=1) from None

    if json_output:
        _print_json([miner.model_dump(mode="json") for miner in miners])
        return

    _render_list_table(miners)


@app.command("info")
def info(
    slug: str,
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Show detailed info for an entity miner."""
    try:
        miner = cast(EntityMiner, HyperscaledClient().miners.get(slug))
    except HyperscaledError as exc:
        console.print(f"[red]Error:[/red] {exc.message}")
        raise typer.Exit(code=1) from None

    if json_output:
        _print_json(miner.model_dump(mode="json"))
        return

    _render_info(miner)


@app.command("compare")
def compare(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Compare entity miners side-by-side."""
    try:
        miners = cast(list[EntityMiner], HyperscaledClient().miners.compare())
    except HyperscaledError as exc:
        console.print(f"[red]Error:[/red] {exc.message}")
        raise typer.Exit(code=1) from None

    if json_output:
        _print_json([miner.model_dump(mode="json") for miner in miners])
        return

    _render_compare(miners)
