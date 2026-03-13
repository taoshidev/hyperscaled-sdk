"""Tests for SDK-006 wallet validation + SDK-007 account setup & balance check."""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from typer.testing import CliRunner

from hyperscaled.cli.main import app
from hyperscaled.exceptions import HyperscaledError
from hyperscaled.models.account import MINIMUM_BALANCE, BalanceStatus
from hyperscaled.sdk.client import HyperscaledClient
from hyperscaled.sdk.config import Config, is_valid_hl_address

VALID_ADDRESS = "0x" + "a1" * 20
MIXED_CASE_ADDRESS = "0xAbCdEf1234567890aBCDef1234567890ABcDeF12"
runner = CliRunner()


# ── SDK-006: Wallet validation ──────────────────────────────


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


# ── SDK-007: Account setup (SDK) ────────────────────────────


class TestAccountSetupSDK:
    """Tests for client.account.setup()."""

    async def test_setup_saves_valid_wallet(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_path = tmp_path / "config.toml"
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", config_path)

        client = HyperscaledClient()
        await client.account.setup_async(VALID_ADDRESS)

        loaded = Config.load(path=config_path)
        assert loaded.wallet.hl_address == VALID_ADDRESS

    async def test_setup_rejects_invalid_wallet(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_path = tmp_path / "config.toml"
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", config_path)

        client = HyperscaledClient()
        with pytest.raises(ValueError, match="Invalid wallet address"):
            await client.account.setup_async("bad")

        loaded = Config.load(path=config_path)
        assert loaded.wallet.hl_address == ""

    async def test_setup_rejects_whitespace_address(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_path = tmp_path / "config.toml"
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", config_path)

        client = HyperscaledClient()
        with pytest.raises(ValueError, match="Invalid wallet address"):
            await client.account.setup_async(" " + VALID_ADDRESS)


# ── SDK-007: Balance check (SDK) ────────────────────────────


def _make_hl_response(equity: str) -> httpx.Response:
    """Construct a fake Hyperliquid clearinghouseState response."""
    return httpx.Response(
        200,
        json={"marginSummary": {"accountValue": equity}},
        request=httpx.Request("POST", "https://api.hyperliquid.xyz/info"),
    )


def _make_hl_error_response(status: int = 500) -> httpx.Response:
    return httpx.Response(
        status,
        json={"error": "internal"},
        request=httpx.Request("POST", "https://api.hyperliquid.xyz/info"),
    )


class TestCheckBalance:
    """Tests for client.account.check_balance()."""

    async def test_healthy_balance(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient(hl_wallet=VALID_ADDRESS)
        await client.open()

        mock_response = _make_hl_response("1250.42")
        client.http.post = AsyncMock(return_value=mock_response)  # type: ignore[method-assign]

        status = await client.account.check_balance_async()
        assert status.balance == Decimal("1250.42")
        assert status.meets_minimum is True
        assert status.minimum_required == MINIMUM_BALANCE

        await client.close()

    async def test_insufficient_balance(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient(hl_wallet=VALID_ADDRESS)
        await client.open()

        mock_response = _make_hl_response("500.00")
        client.http.post = AsyncMock(return_value=mock_response)  # type: ignore[method-assign]

        status = await client.account.check_balance_async()
        assert status.balance == Decimal("500.00")
        assert status.meets_minimum is False

        await client.close()

    async def test_exact_minimum_passes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient(hl_wallet=VALID_ADDRESS)
        await client.open()

        mock_response = _make_hl_response("1000.00")
        client.http.post = AsyncMock(return_value=mock_response)  # type: ignore[method-assign]

        status = await client.account.check_balance_async()
        assert status.balance == Decimal("1000.00")
        assert status.meets_minimum is True

        await client.close()

    async def test_zero_balance(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient(hl_wallet=VALID_ADDRESS)
        await client.open()

        mock_response = _make_hl_response("0")
        client.http.post = AsyncMock(return_value=mock_response)  # type: ignore[method-assign]

        status = await client.account.check_balance_async()
        assert status.balance == Decimal("0")
        assert status.meets_minimum is False

        await client.close()

    async def test_missing_wallet_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient()

        with pytest.raises(HyperscaledError, match="No Hyperliquid wallet configured"):
            await client.account.check_balance_async()

    async def test_explicit_wallet_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        override = "0x" + "bb" * 20
        client = HyperscaledClient()
        await client.open()

        mock_response = _make_hl_response("2000.00")
        client.http.post = AsyncMock(return_value=mock_response)  # type: ignore[method-assign]

        status = await client.account.check_balance_async(override)
        assert status.balance == Decimal("2000.00")
        assert status.meets_minimum is True

        client.http.post.assert_called_once()  # type: ignore[union-attr]
        call_kwargs = client.http.post.call_args  # type: ignore[union-attr]
        assert call_kwargs.kwargs["json"]["user"] == override

        await client.close()

    async def test_hl_api_http_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient(hl_wallet=VALID_ADDRESS)
        await client.open()

        mock_response = _make_hl_error_response(500)
        client.http.post = AsyncMock(return_value=mock_response)  # type: ignore[method-assign]

        with pytest.raises(HyperscaledError, match="Hyperliquid balance request failed"):
            await client.account.check_balance_async()

        await client.close()

    async def test_hl_api_network_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient(hl_wallet=VALID_ADDRESS)
        await client.open()

        client.http.post = AsyncMock(  # type: ignore[method-assign]
            side_effect=httpx.ConnectError("connection refused")
        )

        with pytest.raises(HyperscaledError, match="Hyperliquid balance request failed"):
            await client.account.check_balance_async()

        await client.close()

    async def test_hl_api_unexpected_shape(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient(hl_wallet=VALID_ADDRESS)
        await client.open()

        bad_response = httpx.Response(
            200,
            json={"unexpected": "data"},
            request=httpx.Request("POST", "https://api.hyperliquid.xyz/info"),
        )
        client.http.post = AsyncMock(return_value=bad_response)  # type: ignore[method-assign]

        with pytest.raises(HyperscaledError, match="Unexpected Hyperliquid balance response"):
            await client.account.check_balance_async()

        await client.close()


# ── SDK-007: Watch balance ──────────────────────────────────


class TestWatchBalance:
    """Tests for client.account.watch_balance()."""

    async def test_watch_invokes_callback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient(hl_wallet=VALID_ADDRESS)
        await client.open()

        responses = [
            _make_hl_response("1500.00"),
            _make_hl_response("1450.00"),
        ]
        call_count = 0

        async def mock_post(*args: object, **kwargs: object) -> httpx.Response:
            nonlocal call_count
            idx = min(call_count, len(responses) - 1)
            call_count += 1
            return responses[idx]

        client.http.post = mock_post  # type: ignore[method-assign]

        collected: list[BalanceStatus] = []

        async def on_balance(status: BalanceStatus) -> None:
            collected.append(status)
            if len(collected) >= 2:
                raise asyncio.CancelledError

        with pytest.raises(asyncio.CancelledError):
            await client.account.watch_balance(on_balance, poll_interval=0.01)

        assert len(collected) == 2
        assert collected[0].balance == Decimal("1500.00")
        assert collected[1].balance == Decimal("1450.00")

        await client.close()

    async def test_watch_sync_callback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient(hl_wallet=VALID_ADDRESS)
        await client.open()

        client.http.post = AsyncMock(  # type: ignore[method-assign]
            return_value=_make_hl_response("3000.00")
        )

        collected: list[BalanceStatus] = []

        def on_balance(status: BalanceStatus) -> None:
            collected.append(status)
            if len(collected) >= 1:
                raise asyncio.CancelledError

        with pytest.raises(asyncio.CancelledError):
            await client.account.watch_balance(on_balance, poll_interval=0.01)

        assert len(collected) == 1
        assert collected[0].meets_minimum is True

        await client.close()

    async def test_watch_missing_wallet(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient()

        with pytest.raises(HyperscaledError, match="No Hyperliquid wallet configured"):
            await client.account.watch_balance(lambda s: None)


# ── SDK-007: CLI balance check ──────────────────────────────


class TestAccountCheckCLI:
    """Tests for `hyperscaled account check`."""

    def test_check_healthy_balance(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        config = Config.load(tmp_path / "config.toml")
        config.set_value("wallet.hl_address", VALID_ADDRESS)
        config.save()

        with patch(
            "hyperscaled.sdk.account.AccountClient.check_balance",
            return_value=BalanceStatus(balance=Decimal("2500.00"), meets_minimum=True),
        ):
            result = runner.invoke(app, ["account", "check"])

        assert result.exit_code == 0
        assert "$2,500.00" in result.output
        assert "PASS" in result.output

    def test_check_insufficient_balance(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        config = Config.load(tmp_path / "config.toml")
        config.set_value("wallet.hl_address", VALID_ADDRESS)
        config.save()

        with patch(
            "hyperscaled.sdk.account.AccountClient.check_balance",
            return_value=BalanceStatus(balance=Decimal("250.00"), meets_minimum=False),
        ):
            result = runner.invoke(app, ["account", "check"])

        assert result.exit_code == 0
        assert "$250.00" in result.output
        assert "FAIL" in result.output

    def test_check_json_output(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        config = Config.load(tmp_path / "config.toml")
        config.set_value("wallet.hl_address", VALID_ADDRESS)
        config.save()

        with patch(
            "hyperscaled.sdk.account.AccountClient.check_balance",
            return_value=BalanceStatus(balance=Decimal("1500.00"), meets_minimum=True),
        ):
            result = runner.invoke(app, ["account", "check", "--json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["balance"] == "1500.00"
        assert data["meets_minimum"] is True
        assert data["minimum_required"] == "1000.00"

    def test_check_missing_wallet(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        with patch(
            "hyperscaled.sdk.account.AccountClient.check_balance",
            side_effect=HyperscaledError("No Hyperliquid wallet configured."),
        ):
            result = runner.invoke(app, ["account", "check"])

        assert result.exit_code == 1
        assert "No Hyperliquid wallet configured" in result.output

    def test_check_hl_api_failure(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        with patch(
            "hyperscaled.sdk.account.AccountClient.check_balance",
            side_effect=HyperscaledError("Hyperliquid balance request failed: 500"),
        ):
            result = runner.invoke(app, ["account", "check"])

        assert result.exit_code == 1
        assert "Hyperliquid balance request failed" in result.output

    def test_check_with_wallet_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        override = "0x" + "cc" * 20
        with patch(
            "hyperscaled.sdk.account.AccountClient.check_balance",
            return_value=BalanceStatus(balance=Decimal("5000.00"), meets_minimum=True),
        ) as mock_check:
            result = runner.invoke(app, ["account", "check", "--wallet", override])

        assert result.exit_code == 0
        mock_check.assert_called_once_with(override)
