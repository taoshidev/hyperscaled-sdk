"""Hyperscaled CLI — entry point and top-level command groups."""

from importlib.metadata import version

import typer

from hyperscaled.cli.account import app as account_app
from hyperscaled.cli.backtest import app as backtest_app
from hyperscaled.cli.config import app as config_app
from hyperscaled.cli.data import app as data_app
from hyperscaled.cli.info import app as info_app
from hyperscaled.cli.kyc import app as kyc_app
from hyperscaled.cli.miners import app as miners_app
from hyperscaled.cli.positions import app as positions_app
from hyperscaled.cli.register import app as register_app
from hyperscaled.cli.rules import app as rules_app
from hyperscaled.cli.trade import app as trade_app

app = typer.Typer(
    name="hyperscaled",
    help="CLI for the Hyperscaled funded trading platform on Hyperliquid.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

app.add_typer(config_app, name="config", help="Manage local configuration.")
app.add_typer(data_app, name="data", help="Market data providers and streaming.")
app.add_typer(backtest_app, name="backtest", help="Backtesting with QuantConnect Lean.")
app.add_typer(account_app, name="account", help="Hyperliquid account setup and funding.")
app.add_typer(miners_app, name="miners", help="Browse entity miners and pricing.")
app.add_typer(register_app, name="register", help="Purchase and connect a funded account.")
app.add_typer(trade_app, name="trade", help="Submit and manage trades.")
app.add_typer(positions_app, name="positions", help="Open and historical positions.")
app.add_typer(info_app, name="info", help="Account info and payout history.")
app.add_typer(kyc_app, name="kyc", help="Identity verification (Privado ID).")
app.add_typer(rules_app, name="rules", help="Vanta Network rules and trade validation.")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"hyperscaled {version('hyperscaled')}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool | None = typer.Option(  # noqa: ARG001
        None,
        "--version",
        "-v",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """Hyperscaled — permissionless funded trading on Hyperliquid."""
