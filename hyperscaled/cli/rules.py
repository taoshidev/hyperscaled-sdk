"""CLI commands for Vanta Network rules. Target: Sprint 06."""

import typer

app = typer.Typer(no_args_is_help=True)


@app.command("list")
def list_rules(
    category: str | None = typer.Option(None, help="Filter by category"),
) -> None:
    """List all Vanta Network trading rules."""
    typer.echo(f"Not yet implemented — target: Sprint 06 (SDK-015) [category={category}]")


@app.command("check")
def check(pair: str, size: float) -> None:
    """Validate a hypothetical trade against rules."""
    typer.echo(f"Not yet implemented — target: Sprint 06 (SDK-015) [pair={pair}, size={size}]")
