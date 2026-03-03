"""CLI commands for KYC verification. Target: Sprint 06."""

import typer

app = typer.Typer(no_args_is_help=True)


@app.command("status")
def status() -> None:
    """Check KYC verification status."""
    typer.echo("Not yet implemented — target: Sprint 06 (SDK-014)")


@app.command("start")
def start() -> None:
    """Start the KYC verification flow."""
    typer.echo("Not yet implemented — target: Sprint 06 (SDK-014)")


@app.command("verify")
def verify() -> None:
    """Complete KYC verification."""
    typer.echo("Not yet implemented — target: Sprint 06 (SDK-014)")
