"""CLI commands for entity miner discovery. Wired in SDK-005."""

import typer

app = typer.Typer(no_args_is_help=True)


@app.command("list")
def list_miners() -> None:
    """List all entity miners on Hyperscaled."""
    typer.echo("Not yet implemented — target: Sprint 04 (SDK-005)")


@app.command("info")
def info(slug: str) -> None:
    """Show detailed info for an entity miner."""
    typer.echo(f"Not yet implemented — target: Sprint 04 (SDK-005) [slug={slug}]")


@app.command("compare")
def compare() -> None:
    """Compare entity miners side-by-side."""
    typer.echo("Not yet implemented — target: Sprint 04 (SDK-005)")
