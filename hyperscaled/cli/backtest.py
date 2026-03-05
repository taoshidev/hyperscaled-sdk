"""CLI commands for backtesting. Target: Phase 2."""

import typer

app = typer.Typer(no_args_is_help=True)


@app.command("init")
def init(strategy_name: str) -> None:
    """Scaffold a new backtest strategy."""
    typer.echo(f"Not yet implemented — target: Phase 2 (Sprint 07+) [strategy={strategy_name}]")


@app.command("run")
def run(strategy_file: str) -> None:
    """Run a backtest."""
    typer.echo(f"Not yet implemented — target: Phase 2 (Sprint 07+) [file={strategy_file}]")


@app.command("results")
def results(run_id: str) -> None:
    """View backtest results."""
    typer.echo(f"Not yet implemented — target: Phase 2 (Sprint 07+) [run_id={run_id}]")
