"""CLI commands for funded account registration. Target: Sprint 05."""

import typer

app = typer.Typer(no_args_is_help=True)


@app.command("purchase")
def purchase(
    miner: str = typer.Option(..., help="Entity miner slug"),
    size: int = typer.Option(..., help="Funded account size"),
) -> None:
    """Purchase a funded account through an entity miner."""
    typer.echo(
        f"Not yet implemented — target: Sprint 05 (SDK-007) [miner={miner}, size={size}]"
    )


@app.command("status")
def status() -> None:
    """Check registration status."""
    typer.echo("Not yet implemented — target: Sprint 05 (SDK-008)")
