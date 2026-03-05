"""Tests for SDK-003 — HyperscaledClient core class."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from hyperscaled.sdk.client import HyperscaledClient, _run_sync
from hyperscaled.sdk.config import Config, WalletConfig
from hyperscaled.sdk.miners import MinersClient

VALID_ADDRESS = "0x" + "a1" * 20
VALID_ADDRESS_2 = "0x" + "b2" * 20


# ── Construction & config precedence ────────────────────────


class TestConstruction:
    def test_default_construction(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient()
        assert client.config.wallet.hl_address == ""
        assert client.config.api.hyperscaled_base_url == "https://api.hyperscaled.com"

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
        ("register", "Sprint 05"),
        ("trade", "Sprint 06"),
        ("portfolio", "Sprint 06"),
        ("account", "Sprint 06"),
        ("payouts", "Sprint 06"),
        ("kyc", "Sprint 06"),
        ("rules", "Sprint 06"),
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

    def test_sub_client_settable(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient()
        sentinel = object()
        client.miners = sentinel
        assert client.miners is sentinel

    def test_sub_client_cached(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient()
        sentinel = object()
        client.miners = sentinel
        assert client.miners is client.miners


# ── HTTP session recreation after close ──────────────────────


class TestSessionRecreation:
    async def test_http_recreated_after_close(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient()
        first = client.http
        await client.close()
        assert first.is_closed

        second = client.http
        assert not second.is_closed
        assert second is not first
        await client.close()
