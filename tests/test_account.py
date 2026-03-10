"""Tests for SDK-006 — Hyperliquid wallet validation."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from hyperscaled.cli.main import app
from hyperscaled.sdk.client import HyperscaledClient
from hyperscaled.sdk.config import Config, is_valid_hl_address

VALID_ADDRESS = "0x" + "a1" * 20
MIXED_CASE_ADDRESS = "0xAbCdEf1234567890aBCDef1234567890ABcDeF12"
runner = CliRunner()


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        (VALID_ADDRESS, True),
        (MIXED_CASE_ADDRESS, True),
        ("", False),
        ("0xabc", False),
        ("a1" * 20, False),
        ("  " + VALID_ADDRESS, False),
        (VALID_ADDRESS + " ", False),
        ("0X" + "a1" * 20, False),
        ("0x" + "g1" * 20, False),
    ],
)
def test_is_valid_hl_address(address: str, expected: bool) -> None:
    assert is_valid_hl_address(address) is expected


def test_account_client_validate_wallet_uses_shared_rule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
    client = HyperscaledClient()

    assert client.account.validate_wallet(VALID_ADDRESS) is True
    assert client.account.validate_wallet(" " + VALID_ADDRESS) is False


class TestAccountCLI:
    def test_account_setup_saves_valid_wallet(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_path = tmp_path / "config.toml"
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", config_path)

        result = runner.invoke(app, ["account", "setup", VALID_ADDRESS])

        assert result.exit_code == 0
        assert "Set" in result.output
        assert Config.load(path=config_path).wallet.hl_address == VALID_ADDRESS

    def test_account_setup_rejects_invalid_wallet(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_path = tmp_path / "config.toml"
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", config_path)

        result = runner.invoke(app, ["account", "setup", "bad"])

        assert result.exit_code == 1
        assert "Invalid wallet address" in result.output
        assert Config.load(path=config_path).wallet.hl_address == ""
