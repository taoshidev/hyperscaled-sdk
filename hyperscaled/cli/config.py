"""CLI commands for local configuration management."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from hyperscaled.sdk.config import Config

app = typer.Typer(no_args_is_help=True)
console = Console()


@app.command("set")
def set_value(
    key: str = typer.Argument(help="Dotted config key (e.g. 'wallet.hl_address')"),
    value: str = typer.Argument(help="Value to set"),
) -> None:
    """Set a configuration value.

    Examples:

        hyperscaled config set wallet.hl_address 0xAbC123...

        hyperscaled config set wallet.payout_address 0xDeF456...
    """
    config = Config.load()
    try:
        config.set_value(key, value)
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from None
    config.save()
    console.print(f"[green]Set[/green] {key} = {value}")


@app.command("show")
def show() -> None:
    """Display the current configuration."""
    config = Config.load()

    table = Table(title="Hyperscaled Configuration", show_lines=True)
    table.add_column("Section", style="cyan", no_wrap=True)
    table.add_column("Key", style="bold")
    table.add_column("Value")

    for section_name in ("wallet", "account", "api"):
        section = getattr(config, section_name)
        for field_name, value in section.model_dump().items():
            display = str(value) if value else "[dim]—[/dim]"
            table.add_row(section_name, field_name, display)

    console.print(table)


@app.command("path")
def path() -> None:
    """Print the config file path."""
    config = Config.load()
    typer.echo(str(config._path))
