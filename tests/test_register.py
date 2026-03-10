"""Tests for SDK-006 register CLI wallet validation preflight."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from hyperscaled.cli.main import app
from hyperscaled.sdk.config import Config

runner = CliRunner()
VALID_ADDRESS = "0x" + "a1" * 20


class TestRegisterCLI:
    def test_register_rejects_invalid_wallet_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        result = runner.invoke(
            app,
            ["register", "--miner", "vanta", "--size", "100000", "--hl-wallet", "bad"],
        )

        assert result.exit_code == 1
        assert "Invalid wallet address" in result.output

    def test_register_rejects_missing_configured_wallet(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        result = runner.invoke(app, ["register", "--miner", "vanta", "--size", "100000"])

        assert result.exit_code == 1
        assert "No Hyperliquid wallet configured" in result.output

    def test_register_uses_configured_wallet_when_valid(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_path = tmp_path / "config.toml"
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", config_path)
        config = Config.load(path=config_path)
        config.set_value("wallet.hl_address", VALID_ADDRESS)
        config.save()

        result = runner.invoke(app, ["register", "--miner", "vanta", "--size", "100000"])

        assert result.exit_code == 0
        assert "Not yet implemented" in result.output
        assert VALID_ADDRESS in result.output

    def test_register_purchase_alias_uses_wallet_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        result = runner.invoke(
            app,
            [
                "register",
                "purchase",
                "--miner",
                "vanta",
                "--size",
                "100000",
                "--hl-wallet",
                VALID_ADDRESS,
            ],
        )

        assert result.exit_code == 0
        assert "Not yet implemented" in result.output
        assert VALID_ADDRESS in result.output
