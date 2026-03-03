"""CLI commands for Hyperliquid account setup. Target: Sprint 05."""

import typer

app = typer.Typer(no_args_is_help=True)


@app.command("setup")
def setup() -> None:
    """Set up a Hyperliquid account."""
    typer.echo("Not yet implemented — target: Sprint 05 (SDK-006)")


@app.command("fund")
def fund(amount: float = typer.Option(..., help="USDC amount to fund")) -> None:
    """Fund your Hyperliquid account."""
    typer.echo(f"Not yet implemented — target: Sprint 05 (SDK-006) [amount={amount}]")


@app.command("check")
def check() -> None:
    """Check account balance and minimum requirements."""
    typer.echo("Not yet implemented — target: Sprint 05 (SDK-006)")


@app.command("status")
def status() -> None:
    """Show account status."""
    typer.echo("Not yet implemented — target: Sprint 05 (SDK-006)")
