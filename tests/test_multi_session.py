"""Multi-tenant safety tests for HyperscaledClient.session()."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from hyperscaled.exceptions import HyperscaledError
from hyperscaled.sdk.client import HyperscaledClient
from hyperscaled.sdk.config import Config

VALID_ADDRESS_A = "0x" + "a1" * 20
VALID_ADDRESS_B = "0x" + "b2" * 20

# Anvil dev key — well-known, never used for anything real.
_KEY_A = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
_KEY_B = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"


class TestSessionIsolation:
    """Two session clients in one process must not see each other's credentials."""

    def test_distinct_credentials_dont_cross(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Even with stale env vars set, session clients must ignore them.
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        monkeypatch.setenv("HYPERSCALED_HL_PRIVATE_KEY", _KEY_A)
        monkeypatch.setenv("HYPERSCALED_HL_ADDRESS", VALID_ADDRESS_A)

        client_a = HyperscaledClient.session(hl_wallet=VALID_ADDRESS_A, hl_private_key=_KEY_A)
        client_b = HyperscaledClient.session(hl_wallet=VALID_ADDRESS_B, hl_private_key=_KEY_B)

        assert client_a.resolve_hl_wallet_address() == VALID_ADDRESS_A
        assert client_b.resolve_hl_wallet_address() == VALID_ADDRESS_B
        assert client_a._hl_private_key == _KEY_A
        assert client_b._hl_private_key == _KEY_B
        assert client_a._config is not client_b._config

    def test_session_ignores_env_private_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        monkeypatch.setenv("HYPERSCALED_HL_PRIVATE_KEY", _KEY_A)

        # Build a session without explicit private key — must raise, not fall back to env.
        client = HyperscaledClient.session(hl_wallet=VALID_ADDRESS_A, hl_private_key="")
        with pytest.raises(HyperscaledError, match="No Hyperliquid private key provided"):
            client._resolve_hl_private_key()

    def test_session_ignores_env_wallet_when_no_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        monkeypatch.setenv("HYPERSCALED_HL_PRIVATE_KEY", _KEY_A)

        client = HyperscaledClient.session(hl_wallet="", hl_private_key="")
        with pytest.raises(HyperscaledError, match="No Hyperliquid wallet configured"):
            client.resolve_hl_wallet_address()

    def test_legacy_constructor_still_uses_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Backward compatibility: the non-session constructor keeps its env fallback.
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        monkeypatch.setenv("HYPERSCALED_HL_PRIVATE_KEY", _KEY_A)

        client = HyperscaledClient()
        assert client._resolve_hl_private_key() == _KEY_A


class TestSessionConfigPersistence:
    """Session clients must not write to the shared config file."""

    def test_session_save_is_noop(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        config_path = tmp_path / "config.toml"
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", config_path)

        client = HyperscaledClient.session(hl_wallet=VALID_ADDRESS_A, hl_private_key=_KEY_A)
        client.config.set_value("account.funded_account_size", "50000")
        client.config.save()

        assert not config_path.exists(), "session client must not touch the shared config file"

    def test_session_doesnt_load_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Pre-seed the default config file with someone else's wallet.
        config_path = tmp_path / "config.toml"
        seeded = Config.load(path=config_path)
        seeded.wallet.hl_address = VALID_ADDRESS_B
        seeded.save()
        assert config_path.exists()

        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", config_path)

        client = HyperscaledClient.session(hl_wallet=VALID_ADDRESS_A, hl_private_key=_KEY_A)
        assert client.config.wallet.hl_address == VALID_ADDRESS_A
        # Confirm the pre-seeded value isn't leaking in.
        assert client.config.wallet.hl_address != VALID_ADDRESS_B


class TestInjectedHttpPools:
    """Injected http pools must not be closed when the session client closes."""

    async def test_injected_http_not_owned(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        shared_http = httpx.AsyncClient(base_url="https://example.com")
        shared_validator = httpx.AsyncClient(base_url="https://example.com")

        client = HyperscaledClient.session(
            hl_wallet=VALID_ADDRESS_A,
            hl_private_key=_KEY_A,
            http_client=shared_http,
            validator_http_client=shared_validator,
        )

        assert client._http is shared_http
        assert client._validator_http is shared_validator
        assert client._owns_http is False
        assert client._owns_validator_http is False

        await client.close()
        # The shared pools must survive the close.
        assert not shared_http.is_closed
        assert not shared_validator.is_closed

        await shared_http.aclose()
        await shared_validator.aclose()

    async def test_owned_http_closed_on_close(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        client = HyperscaledClient.session(hl_wallet=VALID_ADDRESS_A, hl_private_key=_KEY_A)
        # Lazy-create both sessions via property access.
        own_http = client.http
        own_validator = client.validator_http
        assert client._owns_http is True
        assert client._owns_validator_http is True

        await client.close()
        assert own_http.is_closed
        assert own_validator.is_closed


class TestConcurrentSessions:
    """Many session clients running concurrently must not interfere."""

    async def test_ten_sessions_concurrent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        wallets = [f"0x{i:02x}" + "0" * 38 for i in range(1, 11)]
        keys = [f"0x{i:064x}" for i in range(1, 11)]

        async def build_and_resolve(w: str, k: str) -> tuple[str, str]:
            c = HyperscaledClient.session(hl_wallet=w, hl_private_key=k)
            return c.resolve_hl_wallet_address(), c._resolve_hl_private_key()

        results = await asyncio.gather(
            *(build_and_resolve(w, k) for w, k in zip(wallets, keys, strict=True))
        )
        for (resolved_w, resolved_k), expected_w, expected_k in zip(
            results, wallets, keys, strict=True
        ):
            assert resolved_w == expected_w
            assert resolved_k == expected_k
