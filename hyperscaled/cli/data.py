"""CLI commands for market data providers. Target: Phase 2."""

import typer

app = typer.Typer(no_args_is_help=True)


@app.command("providers")
def providers() -> None:
    """List available data providers."""
    typer.echo("Not yet implemented — target: Phase 2 (Sprint 07+)")


@app.command("subscribe")
def subscribe(provider: str) -> None:
    """Connect to a data provider."""
    typer.echo(f"Not yet implemented — target: Phase 2 (Sprint 07+) [provider={provider}]")


@app.command("stream")
def stream(provider: str, pairs: str) -> None:
    """Stream real-time market data."""
    typer.echo(
        f"Not yet implemented — target: Phase 2 (Sprint 07+) "
        f"[provider={provider}, pairs={pairs}]"
    )


@app.command("historical")
def historical(
    provider: str,
    pair: str,
    from_date: str = typer.Option(..., "--from", help="Start date"),
    to_date: str = typer.Option(..., "--to", help="End date"),
) -> None:
    """Fetch historical market data."""
    typer.echo(
        f"Not yet implemented — target: Phase 2 (Sprint 07+) "
        f"[provider={provider}, pair={pair}, from={from_date}, to={to_date}]"
    )
