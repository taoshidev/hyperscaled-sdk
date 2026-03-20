"""Tests for SDK-008 (purchase) and SDK-009 (status polling)."""

from __future__ import annotations

import json
import time
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
    RegistrationPollTimeoutError,
    UnsupportedAccountSizeError,
)
from hyperscaled.models import (
    BalanceStatus,
    EntityMiner,
    PricingTier,
    ProfitSplit,
    RegistrationStatus,
)
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
    shared = httpx.AsyncClient(transport=handler, base_url="https://api.example.com")
    client._http = shared
    client._validator_http = shared
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
        monkeypatch.setattr(
            client.register,
            "_sign_payment",
            lambda reqs, key: {"payment-signature": "test-signature"},
        )

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
        monkeypatch.setattr(
            client.register,
            "_sign_payment",
            lambda reqs, key: {"payment-signature": "test-signature"},
        )

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
        monkeypatch.setattr(
            client.register,
            "_sign_payment",
            lambda reqs, key: {"payment-signature": "test-signature"},
        )

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
        monkeypatch.setattr(
            client.register,
            "_sign_payment",
            lambda reqs, key: {"payment-signature": "test-signature"},
        )

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

    def test_payment_wallet_address_from_private_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_client(tmp_path, monkeypatch, httpx.MockTransport(_mock_handler))
        hh = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
        addr = client.register.payment_wallet_address(private_key=hh)
        assert addr.lower() == "0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266"
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

    def check_balance(self, wallet_address: str | None = None) -> BalanceStatus:
        return BalanceStatus(balance=Decimal("5000"), meets_minimum=True)


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

    def payment_wallet_address(self, private_key: str | None = None) -> str:
        return VALID_ADDRESS_2

    def payment_wallet_usdc_balance(self, private_key: str | None = None) -> Decimal:
        return Decimal("500")

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
        assert "Checkout summary" in result.output
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
        assert "Checkout summary" in result.output
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
        assert "Checkout summary" in result.output
        assert "0x999" in result.output
        assert "Account created." in result.output

    def test_register_cli_rejects_unsupported_account_size(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        fake = _FakeClient(
            [_sample_miner()],
            register_result=RegistrationStatus(status="registered", account_size=100_000),
        )
        monkeypatch.setattr("hyperscaled.cli.register.HyperscaledClient", lambda: fake)
        fake.config.set_value("wallet.hl_address", VALID_ADDRESS)

        result = runner.invoke(
            app,
            [
                "register",
                "--miner",
                "vanta",
                "--size",
                "100000",
                "--email",
                "user@example.com",
            ],
        )

        assert result.exit_code == 1
        assert "not offered" in result.output
        assert "$50,000" in result.output or "$25,000" in result.output

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


# ── SDK-009: Status polling tests ────────────────────────────

_STATUS_ACTIVE = {"status": "active", "hl_address": VALID_ADDRESS}
_STATUS_PENDING = {"status": "pending", "hl_address": VALID_ADDRESS}
_STATUS_PROCESSING = {"status": "processing", "hl_address": VALID_ADDRESS}
_STATUS_NOT_FOUND = {"status": "not_found", "hl_address": VALID_ADDRESS}
_STATUS_FAILED = {"status": "failed", "hl_address": VALID_ADDRESS}
_STATUS_ELIMINATED = {"status": "eliminated", "hl_address": VALID_ADDRESS}
_STATUS_REGISTERED_WITH_ACCOUNT = {
    "status": "registered",
    "hl_address": VALID_ADDRESS,
    "funded_account_id": "fa_123",
    "account_size": 100_000,
}


def _status_handler(
    status_response: dict[str, str],
) -> httpx.MockTransport:
    """Build a mock transport that returns a fixed status response."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/registration-status":
            return httpx.Response(200, json=status_response)
        return _mock_handler(request)

    return httpx.MockTransport(handler)


def _sequential_status_handler(
    responses: list[dict[str, str]],
) -> httpx.MockTransport:
    """Build a mock transport that returns status responses in sequence."""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        if request.url.path == "/api/registration-status":
            idx = min(call_count, len(responses) - 1)
            call_count += 1
            return httpx.Response(200, json=responses[idx])
        return _mock_handler(request)

    return httpx.MockTransport(handler)


class TestCheckStatus:
    async def test_check_status_active(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_client(tmp_path, monkeypatch, _status_handler(_STATUS_ACTIVE))
        result = await client.register.check_status_async(VALID_ADDRESS)

        assert result.status == "active"
        assert result.hl_address == VALID_ADDRESS
        assert result.is_terminal is True
        assert result.is_success is True
        await client.close()

    async def test_check_status_pending(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_client(tmp_path, monkeypatch, _status_handler(_STATUS_PENDING))
        result = await client.register.check_status_async(VALID_ADDRESS)

        assert result.status == "pending"
        assert result.is_terminal is False
        assert result.is_success is False
        await client.close()

    async def test_check_status_not_found(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_client(tmp_path, monkeypatch, _status_handler(_STATUS_NOT_FOUND))
        result = await client.register.check_status_async(VALID_ADDRESS)

        assert result.status == "not_found"
        assert result.is_terminal is False
        await client.close()

    async def test_check_status_processing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_client(tmp_path, monkeypatch, _status_handler(_STATUS_PROCESSING))
        result = await client.register.check_status_async(VALID_ADDRESS)

        assert result.status == "processing"
        assert result.is_terminal is False
        assert result.is_success is False
        await client.close()

    async def test_check_status_failed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_client(tmp_path, monkeypatch, _status_handler(_STATUS_FAILED))
        result = await client.register.check_status_async(VALID_ADDRESS)

        assert result.status == "failed"
        assert result.is_terminal is True
        assert result.is_success is False
        await client.close()

    async def test_check_status_eliminated(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_client(tmp_path, monkeypatch, _status_handler(_STATUS_ELIMINATED))
        result = await client.register.check_status_async(VALID_ADDRESS)

        assert result.status == "eliminated"
        assert result.is_terminal is True
        assert result.is_success is False
        await client.close()

    async def test_check_status_persists_funded_account_id_when_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_client(
            tmp_path,
            monkeypatch,
            _status_handler(_STATUS_REGISTERED_WITH_ACCOUNT),
        )
        result = await client.register.check_status_async(VALID_ADDRESS)

        assert result.status == "registered"
        assert result.funded_account_id == "fa_123"
        assert result.account_size == 100_000
        assert client.config.account.funded_account_id == "fa_123"
        await client.close()

    async def test_check_status_rejects_invalid_wallet(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_client(tmp_path, monkeypatch, _status_handler(_STATUS_ACTIVE))
        with pytest.raises(ValueError, match="Invalid HL wallet"):
            await client.register.check_status_async("bad-address")
        await client.close()

    async def test_check_status_backend_400(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/registration-status":
                return httpx.Response(400, json={"error": "Invalid or missing hl_address"})
            return _mock_handler(request)

        client = _make_client(tmp_path, monkeypatch, httpx.MockTransport(handler))
        with pytest.raises(RegistrationError, match="Invalid or missing"):
            await client.register.check_status_async(VALID_ADDRESS)
        await client.close()

    async def test_check_status_backend_502(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/registration-status":
                return httpx.Response(502, json={"error": "Could not reach validator"})
            return _mock_handler(request)

        client = _make_client(tmp_path, monkeypatch, httpx.MockTransport(handler))
        with pytest.raises(RegistrationError, match="502"):
            await client.register.check_status_async(VALID_ADDRESS)
        await client.close()

    def test_check_status_sync(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _make_client(tmp_path, monkeypatch, _status_handler(_STATUS_ACTIVE))
        result = cast(
            RegistrationStatus,
            client.register.check_status(VALID_ADDRESS),
        )
        assert result.status == "active"
        client.close_sync()


class TestPollUntilComplete:
    async def test_poll_immediate_terminal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_client(tmp_path, monkeypatch, _status_handler(_STATUS_ACTIVE))
        statuses: list[str] = []

        result = await client.register.poll_until_complete_async(
            VALID_ADDRESS,
            interval_seconds=0.01,
            on_status=lambda s: statuses.append(s.status),
        )

        assert result.status == "active"
        assert result.is_success is True
        assert statuses == ["active"]
        await client.close()

    async def test_poll_pending_then_active(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        transport = _sequential_status_handler([_STATUS_PENDING, _STATUS_PENDING, _STATUS_ACTIVE])
        client = _make_client(tmp_path, monkeypatch, transport)
        statuses: list[str] = []

        result = await client.register.poll_until_complete_async(
            VALID_ADDRESS,
            interval_seconds=0.01,
            on_status=lambda s: statuses.append(s.status),
        )

        assert result.status == "active"
        assert statuses == ["pending", "pending", "active"]
        await client.close()

    async def test_poll_not_found_then_registered(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        transport = _sequential_status_handler(
            [
                _STATUS_NOT_FOUND,
                _STATUS_PENDING,
                {"status": "registered", "hl_address": VALID_ADDRESS},
            ]
        )
        client = _make_client(tmp_path, monkeypatch, transport)

        result = await client.register.poll_until_complete_async(
            VALID_ADDRESS,
            interval_seconds=0.01,
        )

        assert result.status == "registered"
        assert result.is_success is True
        await client.close()

    async def test_poll_reaches_failed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        transport = _sequential_status_handler([_STATUS_PENDING, _STATUS_FAILED])
        client = _make_client(tmp_path, monkeypatch, transport)

        result = await client.register.poll_until_complete_async(
            VALID_ADDRESS,
            interval_seconds=0.01,
        )

        assert result.status == "failed"
        assert result.is_terminal is True
        assert result.is_success is False
        await client.close()

    async def test_poll_timeout(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _make_client(tmp_path, monkeypatch, _status_handler(_STATUS_PENDING))

        with pytest.raises(RegistrationPollTimeoutError, match="timed out") as exc_info:
            await client.register.poll_until_complete_async(
                VALID_ADDRESS,
                interval_seconds=0.01,
                timeout_seconds=0.05,
            )

        assert exc_info.value.hl_address == VALID_ADDRESS
        assert exc_info.value.last_status == "pending"
        await client.close()

    async def test_poll_timeout_caps_sleep_to_remaining_time(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_client(tmp_path, monkeypatch, _status_handler(_STATUS_PENDING))
        start = time.perf_counter()

        with pytest.raises(RegistrationPollTimeoutError, match="timed out") as exc_info:
            await client.register.poll_until_complete_async(
                VALID_ADDRESS,
                interval_seconds=0.5,
                timeout_seconds=0.05,
            )

        elapsed = time.perf_counter() - start

        assert elapsed < 0.2
        assert exc_info.value.elapsed_seconds < 0.2
        await client.close()

    def test_poll_sync(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _make_client(tmp_path, monkeypatch, _status_handler(_STATUS_ACTIVE))
        result = cast(
            RegistrationStatus,
            client.register.poll_until_complete(
                VALID_ADDRESS,
                interval_seconds=0.01,
            ),
        )
        assert result.status == "active"
        client.close_sync()


# ── SDK-009: Status CLI tests ────────────────────────────────


class _FakeRegisterClientWithStatus(_FakeRegisterClient):
    def __init__(
        self,
        result: RegistrationStatus | None = None,
        error: Exception | None = None,
        status_result: RegistrationStatus | None = None,
        status_error: Exception | None = None,
        poll_result: RegistrationStatus | None = None,
        poll_error: Exception | None = None,
    ):
        super().__init__(result, error)
        self._status_result = status_result
        self._status_error = status_error
        self._poll_result = poll_result
        self._poll_error = poll_error

    def check_status(self, *args: Any, **kwargs: Any) -> RegistrationStatus:
        if self._status_error:
            raise self._status_error
        assert self._status_result is not None
        return self._status_result

    def poll_until_complete(self, *args: Any, **kwargs: Any) -> RegistrationStatus:
        if self._poll_error:
            raise self._poll_error
        assert self._poll_result is not None
        on_status = kwargs.get("on_status")
        if on_status:
            on_status(self._poll_result)
        return self._poll_result


class _FakeClientWithStatus:
    def __init__(
        self,
        register_client: _FakeRegisterClientWithStatus,
    ) -> None:
        self.miners = _FakeMinersClient([_sample_miner()])
        self.account = _FakeAccountClient()
        self.register = register_client
        self.config = Config()


class TestStatusCLI:
    def test_status_no_poll_active(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        reg_client = _FakeRegisterClientWithStatus(
            status_result=RegistrationStatus(status="active", hl_address=VALID_ADDRESS),
        )
        fake = _FakeClientWithStatus(reg_client)
        monkeypatch.setattr("hyperscaled.cli.register.HyperscaledClient", lambda: fake)

        result = runner.invoke(
            app,
            ["register", "status", "--hl-wallet", VALID_ADDRESS, "--no-poll"],
        )

        assert result.exit_code == 0
        assert "active" in result.output
        assert "Registration Status" in result.output

    def test_status_no_poll_json(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        reg_client = _FakeRegisterClientWithStatus(
            status_result=RegistrationStatus(status="pending", hl_address=VALID_ADDRESS),
        )
        fake = _FakeClientWithStatus(reg_client)
        monkeypatch.setattr("hyperscaled.cli.register.HyperscaledClient", lambda: fake)

        result = runner.invoke(
            app,
            ["register", "status", "--hl-wallet", VALID_ADDRESS, "--no-poll", "--json"],
        )

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "pending"
        assert data["hl_address"] == VALID_ADDRESS

    def test_status_poll_completes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        reg_client = _FakeRegisterClientWithStatus(
            poll_result=RegistrationStatus(status="active", hl_address=VALID_ADDRESS),
        )
        fake = _FakeClientWithStatus(reg_client)
        monkeypatch.setattr("hyperscaled.cli.register.HyperscaledClient", lambda: fake)

        result = runner.invoke(
            app,
            ["register", "status", "--hl-wallet", VALID_ADDRESS],
        )

        assert result.exit_code == 0
        assert "Registration Complete" in result.output

    def test_status_poll_timeout(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        reg_client = _FakeRegisterClientWithStatus(
            poll_error=RegistrationPollTimeoutError(
                "Polling timed out after 300s. Last status: pending",
                hl_address=VALID_ADDRESS,
                last_status="pending",
                elapsed_seconds=300.0,
            ),
        )
        fake = _FakeClientWithStatus(reg_client)
        monkeypatch.setattr("hyperscaled.cli.register.HyperscaledClient", lambda: fake)

        result = runner.invoke(
            app,
            ["register", "status", "--hl-wallet", VALID_ADDRESS],
        )

        assert result.exit_code == 2
        assert "Timeout" in result.output

    def test_status_poll_failed_registration(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        reg_client = _FakeRegisterClientWithStatus(
            poll_result=RegistrationStatus(status="failed", hl_address=VALID_ADDRESS),
        )
        fake = _FakeClientWithStatus(reg_client)
        monkeypatch.setattr("hyperscaled.cli.register.HyperscaledClient", lambda: fake)

        result = runner.invoke(
            app,
            ["register", "status", "--hl-wallet", VALID_ADDRESS],
        )

        assert result.exit_code == 1

    def test_status_rejects_invalid_wallet(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        result = runner.invoke(
            app,
            ["register", "status", "--hl-wallet", "bad"],
        )

        assert result.exit_code == 1
        assert "Invalid wallet address" in result.output

    def test_status_no_poll_backend_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        reg_client = _FakeRegisterClientWithStatus(
            status_error=RegistrationError("Could not reach validator", status_code=502),
        )
        fake = _FakeClientWithStatus(reg_client)
        monkeypatch.setattr("hyperscaled.cli.register.HyperscaledClient", lambda: fake)

        result = runner.invoke(
            app,
            ["register", "status", "--hl-wallet", VALID_ADDRESS, "--no-poll"],
        )

        assert result.exit_code == 1
        assert "Could not reach validator" in result.output

    def test_status_no_poll_eliminated_exits_nonzero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        reg_client = _FakeRegisterClientWithStatus(
            status_result=RegistrationStatus(status="eliminated", hl_address=VALID_ADDRESS),
        )
        fake = _FakeClientWithStatus(reg_client)
        monkeypatch.setattr("hyperscaled.cli.register.HyperscaledClient", lambda: fake)

        result = runner.invoke(
            app,
            ["register", "status", "--hl-wallet", VALID_ADDRESS, "--no-poll"],
        )

        assert result.exit_code == 1
        assert "eliminated" in result.output

    def test_status_uses_configured_wallet(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        reg_client = _FakeRegisterClientWithStatus(
            status_result=RegistrationStatus(status="active", hl_address=VALID_ADDRESS),
        )
        fake = _FakeClientWithStatus(reg_client)
        fake.config.set_value("wallet.hl_address", VALID_ADDRESS)
        monkeypatch.setattr("hyperscaled.cli.register.HyperscaledClient", lambda: fake)

        result = runner.invoke(
            app,
            ["register", "status", "--no-poll"],
        )

        assert result.exit_code == 0
        assert "active" in result.output
