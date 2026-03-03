"""CLI commands for account info and payouts. Target: Sprint 06."""

import typer

app = typer.Typer(no_args_is_help=True)


@app.command("account")
def account_info() -> None:
    """Show full account information."""
    typer.echo("Not yet implemented — target: Sprint 06 (SDK-012)")


@app.command("limits")
def limits() -> None:
    """Show account leverage and exposure limits."""
    typer.echo("Not yet implemented — target: Sprint 06 (SDK-012)")


@app.command("payouts")
def payouts(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Show payout history."""
    typer.echo(f"Not yet implemented — target: Sprint 06 (SDK-013) [json={json_output}]")
