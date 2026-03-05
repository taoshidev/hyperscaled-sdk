"""CLI commands for positions and orders. Target: Sprint 06."""

import typer

app = typer.Typer(no_args_is_help=True)


@app.command("open")
def open_positions(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Show open positions."""
    typer.echo(f"Not yet implemented — target: Sprint 06 (SDK-011) [json={json_output}]")


@app.command("history")
def history(
    from_date: str | None = typer.Option(None, "--from", help="Start date"),
    to_date: str | None = typer.Option(None, "--to", help="End date"),
    pair: str | None = typer.Option(None, help="Filter by trading pair"),
) -> None:
    """Show position history."""
    typer.echo(
        f"Not yet implemented — target: Sprint 06 (SDK-011) "
        f"[from={from_date}, to={to_date}, pair={pair}]"
    )
