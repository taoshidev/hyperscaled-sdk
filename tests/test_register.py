"""Tests for SDK-008 — funded account registration purchase."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from typer.testing import CliRunner

from hyperscaled.cli.main import app
from hyperscaled.exceptions import (
    InsufficientBalanceError,
    InvalidMinerError,
    PaymentError,
    RegistrationError,
    UnsupportedAccountSizeError,
)
from hyperscaled.models import EntityMiner, PricingTier, ProfitSplit, RegistrationStatus
from hyperscaled.sdk.client import HyperscaledClient
from hyperscaled.sdk.config import Config

runner = CliRunner()
VALID_ADDRESS = "0x" + "a1" * 20
VALID_ADDRESS_2 = "0x" + "b2" * 20

_MINER_PAYLOAD = {
    "name": "Vanta Trading",
    "slug": "vanta",
    "color": "#3b82f6",
    "payoutCadenceDays": 7,
    "tiers": [
        {"accountSize": 25_000, "priceUsdc": 150, "profitSplit": 80},
        {"accountSize": 50_000, "priceUsdc": 250, "profitSplit": 80},
    ],
}

_BALANCE_RESPONSE = {
    "marginSummary": {"accountValue": "5000.00"},
}

_LOW_BALANCE_RESPONSE = {
    "marginSummary": {"accountValue": "500.00"},
}

_REGISTER_402_BODY = {
    "x402Version": 2,
    "accepts": [
        {
            "scheme": "exact",
            "network": "base",
            "asset": "0xusdc",
            "amount": "150000000",
            "payTo": "0xminer",
            "maxTimeoutSeconds": 300,
        }
    ],
}

_REGISTER_200_BODY = {
    "status": "registered",
    "message": "Your trading account has been created.",
    "txHash": "0xabc123",
}


def _make_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    handler: httpx.MockTransport,
) -> HyperscaledClient:
    monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
    client = HyperscaledClient(base_url="https://api.example.com")
    client._http = httpx.AsyncClient(transport=handler, base_url="https://api.example.com")
    return client


def _mock_handler(request: httpx.Request) -> httpx.Response:
    """Route mock requests by URL path."""
    path = request.url.path

    if path == "/info" or request.url.host == "api.hyperliquid.xyz":
        return httpx.Response(200, json=_BALANCE_RESPONSE)

    if path == "/api/entity":
        return httpx.Response(200, json=[_MINER_PAYLOAD])

    if path == "/api/register":
        body = json.loads(request.content.decode())
        if not body.get("email"):
            return httpx.Response(400, json={"error": "Missing required fields"})
        has_payment = request.headers.get("payment-signature")
        if has_payment:
            return httpx.Response(200, json=_REGISTER_200_BODY)
        return httpx.Response(402, json=_REGISTER_402_BODY)

    return httpx.Response(404, json={"error": "unknown"})


class TestRegisterClient:
    async def test_purchase_rejects_invalid_hl_wallet(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_client(tmp_path, monkeypatch, httpx.MockTransport(_mock_handler))

        with pytest.raises(ValueError, match="Invalid HL wallet"):
            await client.register.purchase_async(
                "vanta", 25_000, "bad-wallet", email="user@example.com", private_key="0xkey"
            )

        await client.close()

    async def test_purchase_rejects_invalid_payout_wallet(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_client(tmp_path, monkeypatch, httpx.MockTransport(_mock_handler))

        with pytest.raises(ValueError, match="Invalid payout wallet"):
            await client.register.purchase_async(
                "vanta",
                25_000,
                VALID_ADDRESS,
                "bad-payout",
                email="user@example.com",
                private_key="0xkey",
            )

        await client.close()

    async def test_purchase_fails_insufficient_balance(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def low_balance_handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "api.hyperliquid.xyz":
                return httpx.Response(200, json=_LOW_BALANCE_RESPONSE)
            return _mock_handler(request)

        client = _make_client(tmp_path, monkeypatch, httpx.MockTransport(low_balance_handler))

        with pytest.raises(InsufficientBalanceError):
            await client.register.purchase_async(
                "vanta", 25_000, VALID_ADDRESS, email="user@example.com", private_key="0xkey"
            )

        await client.close()

    async def test_purchase_fails_invalid_miner(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_client(tmp_path, monkeypatch, httpx.MockTransport(_mock_handler))

        with pytest.raises(InvalidMinerError, match="not found"):
            await client.register.purchase_async(
                "nonexistent",
                25_000,
                VALID_ADDRESS,
                email="user@example.com",
                private_key="0xkey",
            )

        await client.close()

    async def test_purchase_fails_unsupported_size(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_client(tmp_path, monkeypatch, httpx.MockTransport(_mock_handler))

        with pytest.raises(UnsupportedAccountSizeError, match="100,000"):
            await client.register.purchase_async(
                "vanta", 100_000, VALID_ADDRESS, email="user@example.com", private_key="0xkey"
            )

        await client.close()

    async def test_purchase_fails_missing_private_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("HYPERSCALED_BASE_PRIVATE_KEY", raising=False)
        client = _make_client(tmp_path, monkeypatch, httpx.MockTransport(_mock_handler))

        with pytest.raises(PaymentError, match="No Base private key"):
            await client.register.purchase_async(
                "vanta",
                25_000,
                VALID_ADDRESS,
                email="user@example.com",
            )

        await client.close()

    async def test_purchase_fails_missing_email(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_client(tmp_path, monkeypatch, httpx.MockTransport(_mock_handler))

        with pytest.raises(ValueError, match="Email is required"):
            await client.register.purchase_async(
                "vanta", 25_000, VALID_ADDRESS, email="", private_key="0xkey"
            )

        await client.close()

    async def test_purchase_happy_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_client(tmp_path, monkeypatch, httpx.MockTransport(_mock_handler))

        # Monkeypatch _sign_payment to avoid real x402 dependency
        monkeypatch.setattr(client.register, "_sign_payment", lambda reqs, key: "test-signature")

        result = await client.register.purchase_async(
            "vanta",
            25_000,
            VALID_ADDRESS,
            email="user@example.com",
            private_key="0xfakekey",
        )

        assert isinstance(result, RegistrationStatus)
        assert result.status == "registered"
        assert result.registration_id is None
        assert result.tx_hash == "0xabc123"
        assert result.message == "Your trading account has been created."
        assert result.account_size == 25_000

        await client.close()

    async def test_purchase_omits_payout_wallet_when_not_provided(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen_bodies: list[dict[str, Any]] = []

        def capture_handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "api.hyperliquid.xyz":
                return httpx.Response(200, json=_BALANCE_RESPONSE)
            if request.url.path == "/api/entity":
                return httpx.Response(200, json=[_MINER_PAYLOAD])
            if request.url.path == "/api/register":
                body = json.loads(request.content.decode())
                seen_bodies.append(body)
                if request.headers.get("payment-signature"):
                    return httpx.Response(200, json=_REGISTER_200_BODY)
                return httpx.Response(402, json=_REGISTER_402_BODY)
            return httpx.Response(404, json={"error": "unknown"})

        client = _make_client(tmp_path, monkeypatch, httpx.MockTransport(capture_handler))
        monkeypatch.setattr(client.register, "_sign_payment", lambda reqs, key: "test-signature")

        await client.register.purchase_async(
            "vanta",
            25_000,
            VALID_ADDRESS,
            email="user@example.com",
            private_key="0xfakekey",
        )

        assert len(seen_bodies) == 2
        assert "payoutAddress" not in seen_bodies[0]
        assert seen_bodies[0]["email"] == "user@example.com"
        await client.close()

    async def test_purchase_payment_settlement_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """402 followed by 500 on paid POST → RegistrationError."""

        call_count = 0

        def failing_paid_handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            if request.url.path == "/api/register":
                call_count += 1
                if request.headers.get("payment-signature"):
                    return httpx.Response(
                        500,
                        json={"error": "Payment settlement failed"},
                    )
                return httpx.Response(402, json=_REGISTER_402_BODY)
            return _mock_handler(request)

        client = _make_client(tmp_path, monkeypatch, httpx.MockTransport(failing_paid_handler))
        monkeypatch.setattr(client.register, "_sign_payment", lambda reqs, key: "test-signature")

        with pytest.raises(RegistrationError, match="500"):
            await client.register.purchase_async(
                "vanta",
                25_000,
                VALID_ADDRESS,
                email="user@example.com",
                private_key="0xfakekey",
            )

        await client.close()

    def test_purchase_sync_outside_event_loop(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_client(tmp_path, monkeypatch, httpx.MockTransport(_mock_handler))
        monkeypatch.setattr(client.register, "_sign_payment", lambda reqs, key: "test-signature")

        result = cast(
            RegistrationStatus,
            client.register.purchase(
                "vanta",
                25_000,
                VALID_ADDRESS,
                email="user@example.com",
                private_key="0xfakekey",
            ),
        )

        assert result.status == "registered"
        assert result.account_size == 25_000
        client.close_sync()


# ── CLI tests ────────────────────────────────────────────────


def _sample_miner() -> EntityMiner:
    split = ProfitSplit(trader_pct=80, miner_pct=20)
    return EntityMiner(
        name="Vanta Trading",
        slug="vanta",
        pricing_tiers=[
            PricingTier(account_size=25_000, cost=Decimal("150.00"), profit_split=split),
            PricingTier(account_size=50_000, cost=Decimal("250.00"), profit_split=split),
        ],
        payout_cadence="weekly",
        available_account_sizes=[25_000, 50_000],
    )


class _FakeAccountClient:
    def validate_wallet(self, address: str) -> bool:
        import re

        return bool(re.fullmatch(r"0x[a-fA-F0-9]{40}", address))


class _FakeMinersClient:
    def __init__(self, miners: list[EntityMiner]) -> None:
        self._miners = miners

    def get(self, slug: str) -> EntityMiner:
        for m in self._miners:
            if m.slug == slug:
                return m
        from hyperscaled.exceptions import HyperscaledError

        raise HyperscaledError(f"Miner '{slug}' not found.")


class _FakeRegisterClient:
    def __init__(self, result: RegistrationStatus | None = None, error: Exception | None = None):
        self._result = result
        self._error = error

    def purchase(self, *args: Any, **kwargs: Any) -> RegistrationStatus:
        if self._error:
            raise self._error
        assert self._result is not None
        return self._result


class _FakeClient:
    def __init__(
        self,
        miners: list[EntityMiner],
        register_result: RegistrationStatus | None = None,
        register_error: Exception | None = None,
    ) -> None:
        self.miners = _FakeMinersClient(miners)
        self.account = _FakeAccountClient()
        self.register = _FakeRegisterClient(register_result, register_error)
        self.config = Config()


class TestRegisterCLI:
    def test_register_rejects_invalid_wallet_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        result = runner.invoke(
            app,
            [
                "register",
                "--miner",
                "vanta",
                "--size",
                "100000",
                "--hl-wallet",
                "bad",
                "--email",
                "user@example.com",
            ],
        )

        assert result.exit_code == 1
        assert "Invalid wallet address" in result.output

    def test_register_rejects_missing_configured_wallet(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        result = runner.invoke(
            app,
            ["register", "--miner", "vanta", "--size", "100000", "--email", "user@example.com"],
        )

        assert result.exit_code == 1
        assert "No Hyperliquid wallet configured" in result.output

    def test_register_uses_configured_wallet_when_valid(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        fake = _FakeClient(
            [_sample_miner()],
            register_result=RegistrationStatus(
                status="registered",
                registration_id="reg-001",
                account_size=25_000,
                tx_hash="0xabc",
                message="Done",
            ),
        )
        fake.config.set_value("wallet.hl_address", VALID_ADDRESS)
        monkeypatch.setattr("hyperscaled.cli.register.HyperscaledClient", lambda: fake)

        result = runner.invoke(
            app,
            ["register", "--miner", "vanta", "--size", "25000", "--email", "user@example.com"],
            input="y\n",
        )

        assert result.exit_code == 0
        assert "Registration Result" in result.output
        assert "registered" in result.output

    def test_register_purchase_alias_uses_wallet_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        fake = _FakeClient(
            [_sample_miner()],
            register_result=RegistrationStatus(
                status="registered",
                registration_id="reg-002",
                account_size=25_000,
                tx_hash="0xdef",
            ),
        )
        monkeypatch.setattr("hyperscaled.cli.register.HyperscaledClient", lambda: fake)

        result = runner.invoke(
            app,
            [
                "register",
                "purchase",
                "--miner",
                "vanta",
                "--size",
                "25000",
                "--hl-wallet",
                VALID_ADDRESS,
                "--email",
                "user@example.com",
            ],
            input="y\n",
        )

        assert result.exit_code == 0
        assert "Registration Result" in result.output

    def test_register_purchase_happy_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        fake = _FakeClient(
            [_sample_miner()],
            register_result=RegistrationStatus(
                status="registered",
                registration_id="reg-003",
                account_size=50_000,
                tx_hash="0x999",
                message="Account created.",
            ),
        )
        monkeypatch.setattr("hyperscaled.cli.register.HyperscaledClient", lambda: fake)

        result = runner.invoke(
            app,
            [
                "register",
                "--miner",
                "vanta",
                "--size",
                "50000",
                "--hl-wallet",
                VALID_ADDRESS,
                "--email",
                "user@example.com",
            ],
            input="y\n",
        )

        assert result.exit_code == 0
        assert "0x999" in result.output
        assert "Account created." in result.output

    def test_register_purchase_insufficient_balance(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        fake = _FakeClient(
            [_sample_miner()],
            register_error=InsufficientBalanceError(
                "Balance too low",
                rule_id="min_balance",
                limit="1000",
                actual_value="500",
                balance=Decimal("500"),
                minimum_required=Decimal("1000"),
            ),
        )
        monkeypatch.setattr("hyperscaled.cli.register.HyperscaledClient", lambda: fake)

        result = runner.invoke(
            app,
            [
                "register",
                "--miner",
                "vanta",
                "--size",
                "25000",
                "--hl-wallet",
                VALID_ADDRESS,
                "--email",
                "user@example.com",
            ],
            input="y\n",
        )

        assert result.exit_code == 1
        assert "Balance too low" in result.output

    def test_register_purchase_payment_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        fake = _FakeClient(
            [_sample_miner()],
            register_error=PaymentError("x402 signing failed"),
        )
        monkeypatch.setattr("hyperscaled.cli.register.HyperscaledClient", lambda: fake)

        result = runner.invoke(
            app,
            [
                "register",
                "--miner",
                "vanta",
                "--size",
                "25000",
                "--hl-wallet",
                VALID_ADDRESS,
                "--email",
                "user@example.com",
            ],
            input="y\n",
        )

        assert result.exit_code == 1
        assert "Payment Error" in result.output

    def test_register_purchase_invalid_miner(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        fake = _FakeClient(
            [],  # no miners
            register_error=InvalidMinerError("Miner 'bad' not found", slug="bad"),
        )
        # Override the miners client to not fail on get()
        fake.miners = _FakeMinersClient([_sample_miner()])
        monkeypatch.setattr("hyperscaled.cli.register.HyperscaledClient", lambda: fake)

        result = runner.invoke(
            app,
            [
                "register",
                "--miner",
                "vanta",
                "--size",
                "25000",
                "--hl-wallet",
                VALID_ADDRESS,
                "--email",
                "user@example.com",
            ],
            input="y\n",
        )

        assert result.exit_code == 1
        assert "not found" in result.output
