"""Tests for SDK-003 — HyperscaledClient core class."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from hyperscaled.exceptions import HyperscaledError
from hyperscaled.sdk.account import AccountClient
from hyperscaled.sdk.client import HyperscaledClient, _run_sync
from hyperscaled.sdk.config import Config, WalletConfig
from hyperscaled.sdk.miners import MinersClient
from hyperscaled.sdk.payouts import PayoutsClient
from hyperscaled.sdk.portfolio import PortfolioClient
from hyperscaled.sdk.register import RegisterClient
from hyperscaled.sdk.rules import RulesClient
from hyperscaled.sdk.trading import TradingClient

VALID_ADDRESS = "0x" + "a1" * 20
VALID_ADDRESS_2 = "0x" + "b2" * 20


# ── Construction & config precedence ────────────────────────


class TestConstruction:
    def test_default_construction(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient()
        assert client.config.wallet.hl_address == ""
        assert client.config.api.hyperscaled_base_url == "https://api.hyperscaled.com"
        assert client.config.api.validator_api_url == "http://34.187.154.219:48888"

    def test_constructor_overrides_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_path = tmp_path / "config.toml"
        config = Config()
        config._path = config_path
        config.wallet = WalletConfig(hl_address=VALID_ADDRESS)
        config.save()

        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", config_path)
        client = HyperscaledClient(hl_wallet=VALID_ADDRESS_2)
        assert client.config.wallet.hl_address == VALID_ADDRESS_2

    def test_constructor_overrides_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        monkeypatch.setenv("HYPERSCALED_HL_ADDRESS", VALID_ADDRESS)
        client = HyperscaledClient(hl_wallet=VALID_ADDRESS_2)
        assert client.config.wallet.hl_address == VALID_ADDRESS_2

    def test_config_file_overrides_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_path = tmp_path / "config.toml"
        config = Config()
        config._path = config_path
        config.wallet = WalletConfig(hl_address=VALID_ADDRESS)
        config.save()

        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", config_path)
        monkeypatch.setenv("HYPERSCALED_HL_ADDRESS", VALID_ADDRESS_2)
        client = HyperscaledClient()
        assert client.config.wallet.hl_address == VALID_ADDRESS

    def test_payout_wallet_override(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient(payout_wallet=VALID_ADDRESS)
        assert client.config.wallet.payout_address == VALID_ADDRESS

    def test_base_url_override(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient(base_url="https://custom.api.com")
        assert client.config.api.hyperscaled_base_url == "https://custom.api.com"


# ── resolve_hl_wallet_address ────────────────────────────────

_ANVIL_DEV_KEY = (
    "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
)


class TestResolveHlWalletAddress:
    def test_uses_config_when_set(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        monkeypatch.setenv("HYPERSCALED_HL_PRIVATE_KEY", _ANVIL_DEV_KEY)
        client = HyperscaledClient(hl_wallet=VALID_ADDRESS)
        assert client.resolve_hl_wallet_address() == VALID_ADDRESS

    def test_derives_from_env_private_key_when_no_config_address(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from eth_account import Account

        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        monkeypatch.setenv("HYPERSCALED_HL_PRIVATE_KEY", _ANVIL_DEV_KEY)
        client = HyperscaledClient()
        assert client.resolve_hl_wallet_address() == Account.from_key(_ANVIL_DEV_KEY).address

    def test_raises_when_no_address_and_no_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        monkeypatch.delenv("HYPERSCALED_HL_PRIVATE_KEY", raising=False)
        client = HyperscaledClient()
        with pytest.raises(HyperscaledError, match="No Hyperliquid wallet configured"):
            client.resolve_hl_wallet_address()


# ── HTTP session ─────────────────────────────────────────────


class TestHTTPSession:
    def test_http_lazy_creation(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient()
        assert client._http is None
        _ = client.http
        assert client._http is not None
        assert isinstance(client._http, httpx.AsyncClient)

    def test_http_uses_base_url(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient(base_url="https://custom.api.com")
        assert str(client.http.base_url) == "https://custom.api.com"

    def test_validator_http_uses_validator_api_url(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient(validator_api_url="http://custom.validator:1")
        assert str(client.validator_http.base_url) == "http://custom.validator:1"

    def test_http_default_headers(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient()
        assert client.http.headers["user-agent"] == "hyperscaled-sdk"

    def test_http_reused_across_accesses(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient()
        first = client.http
        second = client.http
        assert first is second


# ── Async context manager ────────────────────────────────────


class TestAsyncContextManager:
    async def test_async_with_opens_and_closes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        async with HyperscaledClient() as client:
            assert client._http is not None
            assert not client._http.is_closed
            session = client._http

        assert session.is_closed

    async def test_async_with_returns_client(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        async with HyperscaledClient() as client:
            assert isinstance(client, HyperscaledClient)


# ── Sync helpers ─────────────────────────────────────────────


class TestSyncHelpers:
    def test_open_sync(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient()
        result = client.open_sync()
        assert result is client
        assert client._http is not None
        assert not client._http.is_closed
        client.close_sync()

    def test_close_sync(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient()
        client.open_sync()
        session = client._http
        assert session is not None
        client.close_sync()
        assert session.is_closed

    def test_run_sync_raises_in_running_loop(self) -> None:
        async def _inner() -> None:
            with pytest.raises(RuntimeError, match="running event loop"):
                _run_sync(asyncio.sleep(0))

        asyncio.run(_inner())


# ── Lazy sub-clients ─────────────────────────────────────────


class TestLazySubClients:
    STUBS = [
        ("data", "Phase 2"),
        ("backtest", "Phase 2"),
    ]

    @pytest.mark.parametrize("attr,target", STUBS)
    def test_unimplemented_sub_client_raises(
        self, attr: str, target: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient()
        with pytest.raises(NotImplementedError, match=target):
            getattr(client, attr)

    def test_miners_lazy_loaded(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient()
        assert getattr(client, "_miners", None) is None

        miners = client.miners

        assert isinstance(miners, MinersClient)
        assert client._miners is miners

    def test_account_lazy_loaded(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient()
        assert getattr(client, "_account", None) is None

        account = client.account

        assert isinstance(account, AccountClient)
        assert client._account is account

    def test_register_lazy_loaded(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient()
        assert getattr(client, "_register", None) is None

        register = client.register

        assert isinstance(register, RegisterClient)
        assert client._register is register

    def test_trade_lazy_loaded(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient()
        assert getattr(client, "_trade", None) is None

        trade = client.trade

        assert isinstance(trade, TradingClient)
        assert client._trade is trade

    def test_payouts_lazy_loaded(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient()
        assert getattr(client, "_payouts", None) is None

        payouts = client.payouts

        assert isinstance(payouts, PayoutsClient)
        assert client._payouts is payouts

    def test_sub_client_settable(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient()
        sentinel = object()
        client.miners = sentinel
        assert client.miners is sentinel
        client.account = sentinel
        assert client.account is sentinel
        client.register = sentinel
        assert client.register is sentinel
        client.trade = sentinel
        assert client.trade is sentinel
        client.rules = sentinel
        assert client.rules is sentinel
        client.portfolio = sentinel
        assert client.portfolio is sentinel

    def test_sub_client_cached(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient()
        sentinel = object()
        client.miners = sentinel
        assert client.miners is client.miners

    def test_rules_lazy_loaded(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient()
        assert getattr(client, "_rules", None) is None

        rules = client.rules

        assert isinstance(rules, RulesClient)
        assert client._rules is rules

    def test_portfolio_lazy_loaded(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient()
        assert getattr(client, "_portfolio", None) is None

        portfolio = client.portfolio

        assert isinstance(portfolio, PortfolioClient)
        assert client._portfolio is portfolio


# ── HTTP session recreation after close ──────────────────────


class TestSessionRecreation:
    async def test_http_recreated_after_close(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient()
        first = client.http
        first_v = client.validator_http
        await client.close()
        assert first.is_closed
        assert first_v.is_closed

        second = client.http
        second_v = client.validator_http
        assert not second.is_closed
        assert not second_v.is_closed
        assert second is not first
        assert second_v is not first_v
        await client.close()
