"""Verify all stub modules import cleanly."""

import importlib

MODULES = [
    "hyperscaled",
    "hyperscaled.exceptions",
    "hyperscaled.models",
    "hyperscaled.cli",
    "hyperscaled.cli.main",
    "hyperscaled.cli.data",
    "hyperscaled.cli.backtest",
    "hyperscaled.cli.account",
    "hyperscaled.cli.miners",
    "hyperscaled.cli.register",
    "hyperscaled.cli.trade",
    "hyperscaled.cli.positions",
    "hyperscaled.cli.info",
    "hyperscaled.cli.kyc",
    "hyperscaled.cli.rules",
    "hyperscaled.sdk.config",
    "hyperscaled.cli.config",
    "hyperscaled.sdk",
    "hyperscaled.sdk.client",
    "hyperscaled.sdk.data",
    "hyperscaled.sdk.backtest",
    "hyperscaled.sdk.account",
    "hyperscaled.sdk.trading",
    "hyperscaled.sdk.portfolio",
    "hyperscaled.sdk.payouts",
    "hyperscaled.sdk.rules",
]


def test_all_modules_import() -> None:
    for module_name in MODULES:
        mod = importlib.import_module(module_name)
        assert mod is not None, f"Failed to import {module_name}"


def test_hyperscaled_client_importable() -> None:
    from hyperscaled import HyperscaledClient

    client = HyperscaledClient()
    assert client is not None


def test_hyperscaled_version() -> None:
    from hyperscaled import __version__

    assert isinstance(__version__, str)
    assert len(__version__) > 0


def test_hyperscaled_error_importable() -> None:
    from hyperscaled.exceptions import HyperscaledError

    err = HyperscaledError("test error")
    assert err.message == "test error"
    assert str(err) == "test error"
