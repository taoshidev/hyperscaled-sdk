"""Tests for SDK-002 — config system."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from hyperscaled.cli.main import app
from hyperscaled.sdk.config import Config, WalletConfig

runner = CliRunner()

VALID_ADDRESS = "0x" + "a1" * 20  # 0xa1a1...a1 (40 hex chars)
VALID_ADDRESS_2 = "0x" + "b2" * 20


# ── Config model ────────────────────────────────────────────


class TestConfigModel:
    def test_defaults(self) -> None:
        config = Config()
        assert config.wallet.hl_address == ""
        assert config.wallet.payout_address == ""
        assert config.account.entity_miner == ""
        assert config.account.funded_account_id == ""
        assert config.account.kyc_status == "not_started"
        assert config.api.hyperscaled_base_url == "https://api.hyperscaled.com"

    def test_valid_address_accepted(self) -> None:
        wallet = WalletConfig(hl_address=VALID_ADDRESS)
        assert wallet.hl_address == VALID_ADDRESS

    def test_empty_address_accepted(self) -> None:
        wallet = WalletConfig(hl_address="")
        assert wallet.hl_address == ""

    def test_invalid_address_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Invalid wallet address"):
            WalletConfig(hl_address="not-an-address")

    def test_short_address_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Invalid wallet address"):
            WalletConfig(hl_address="0xabc")

    def test_missing_prefix_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Invalid wallet address"):
            WalletConfig(hl_address="a1" * 20)

    def test_invalid_kyc_status_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Config(account={"kyc_status": "bogus"})  # type: ignore[arg-type]

    def test_json_roundtrip(self) -> None:
        config = Config(wallet=WalletConfig(hl_address=VALID_ADDRESS))
        data = config.model_dump_json()
        restored = Config.model_validate_json(data)
        assert restored.wallet.hl_address == VALID_ADDRESS


# ── Load / save ─────────────────────────────────────────────


class TestLoadSave:
    def test_auto_creates_on_first_load(self, tmp_path: Path) -> None:
        config_path = tmp_path / ".hyperscaled" / "config.toml"
        assert not config_path.exists()

        config = Config.load(path=config_path)

        assert config_path.exists()
        assert config.wallet.hl_address == ""

    def test_save_and_reload(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.toml"
        config = Config()
        config._path = config_path
        config.wallet = WalletConfig(hl_address=VALID_ADDRESS)
        config.save()

        loaded = Config.load(path=config_path)
        assert loaded.wallet.hl_address == VALID_ADDRESS

    def test_set_value_wallet(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.toml"
        config = Config.load(path=config_path)
        config.set_value("wallet.hl_address", VALID_ADDRESS)
        config.save()

        reloaded = Config.load(path=config_path)
        assert reloaded.wallet.hl_address == VALID_ADDRESS

    def test_set_value_validates(self) -> None:
        config = Config()
        with pytest.raises(ValueError, match="Invalid wallet address"):
            config.set_value("wallet.hl_address", "bad")

    def test_set_value_bad_section(self) -> None:
        config = Config()
        with pytest.raises(ValueError, match="Unknown config section"):
            config.set_value("nosection.key", "val")

    def test_set_value_bad_key(self) -> None:
        config = Config()
        with pytest.raises(ValueError, match="Unknown key"):
            config.set_value("wallet.nonexistent", "val")

    def test_set_value_bad_format(self) -> None:
        config = Config()
        with pytest.raises(ValueError, match="expected format"):
            config.set_value("justonepart", "val")


# ── Env var fallbacks ───────────────────────────────────────


class TestEnvVarFallbacks:
    def test_hl_address_from_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        config_path = tmp_path / "config.toml"
        monkeypatch.setenv("HYPERSCALED_HL_ADDRESS", VALID_ADDRESS)

        config = Config.load(path=config_path)
        assert config.wallet.hl_address == VALID_ADDRESS

    def test_payout_address_from_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        config_path = tmp_path / "config.toml"
        monkeypatch.setenv("HYPERSCALED_PAYOUT_ADDRESS", VALID_ADDRESS)

        config = Config.load(path=config_path)
        assert config.wallet.payout_address == VALID_ADDRESS

    def test_base_url_from_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        config_path = tmp_path / "config.toml"
        monkeypatch.setenv("HYPERSCALED_BASE_URL", "https://custom.api.com")

        config = Config.load(path=config_path)
        assert config.api.hyperscaled_base_url == "https://custom.api.com"

    def test_file_value_takes_precedence_over_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_path = tmp_path / "config.toml"
        config = Config()
        config._path = config_path
        config.wallet = WalletConfig(hl_address=VALID_ADDRESS)
        config.save()

        monkeypatch.setenv("HYPERSCALED_HL_ADDRESS", VALID_ADDRESS_2)

        loaded = Config.load(path=config_path)
        assert loaded.wallet.hl_address == VALID_ADDRESS


# ── CLI commands ────────────────────────────────────────────


class TestCLI:
    def test_config_show(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        config_path = tmp_path / "config.toml"
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", config_path)

        result = runner.invoke(app, ["config", "show"])
        assert result.exit_code == 0
        assert "Hyperscaled Configuration" in result.output

    def test_config_set_valid(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        config_path = tmp_path / "config.toml"
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", config_path)

        result = runner.invoke(app, ["config", "set", "wallet.hl_address", VALID_ADDRESS])
        assert result.exit_code == 0
        assert "Set" in result.output

        loaded = Config.load(path=config_path)
        assert loaded.wallet.hl_address == VALID_ADDRESS

    def test_config_set_invalid_address(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_path = tmp_path / "config.toml"
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", config_path)

        result = runner.invoke(app, ["config", "set", "wallet.hl_address", "bad"])
        assert result.exit_code == 1
        assert "Error" in result.output

    def test_config_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        config_path = tmp_path / "config.toml"
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", config_path)

        result = runner.invoke(app, ["config", "path"])
        assert result.exit_code == 0
        assert str(config_path) in result.output
