"""Tests for SDK-010 — Trade Submission."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hyperscaled.exceptions import HyperscaledError
from hyperscaled.models.account import BalanceStatus
from hyperscaled.models.trading import Order
from hyperscaled.sdk.client import HyperscaledClient
from hyperscaled.sdk.pairs import normalize_pair_to_hl, normalize_pair_to_vanta, validate_pair
from hyperscaled.sdk.trading import TradingClient

VALID_ADDRESS = "0x" + "a1" * 20


def _hl_filled_response(
    oid: int = 123456,
    total_sz: str = "0.01",
    avg_px: str = "100250.50",
) -> dict:
    return {
        "status": "ok",
        "response": {
            "type": "order",
            "data": {
                "statuses": [
                    {"filled": {"totalSz": total_sz, "avgPx": avg_px, "oid": oid}}
                ]
            },
        },
    }


def _hl_resting_response(oid: int = 123456) -> dict:
    return {
        "status": "ok",
        "response": {
            "type": "order",
            "data": {
                "statuses": [{"resting": {"oid": oid}}]
            },
        },
    }


def _hl_error_response(error: str = "Insufficient margin") -> dict:
    return {
        "status": "ok",
        "response": {
            "type": "order",
            "data": {
                "statuses": [{"error": error}]
            },
        },
    }


def _hl_top_level_failure() -> dict:
    return {"status": "err", "response": "Rate limited"}


@pytest.fixture()
def trading_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> HyperscaledClient:
    monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
    monkeypatch.setenv("HYPERSCALED_HL_PRIVATE_KEY", "0x" + "ab" * 32)

    client = HyperscaledClient()
    client.config.set_value("wallet.hl_address", VALID_ADDRESS)
    client.config.set_value("account.funded_account_size", "100000")

    async def mock_balance(*_args: object, **_kwargs: object) -> BalanceStatus:
        return BalanceStatus(balance=Decimal("1000"), meets_minimum=True)

    client.account.check_balance_async = mock_balance  # type: ignore[assignment]

    return client


# ── Pair utilities ────────────────────────────────────────────


class TestPairUtilities:
    def test_validate_pair_valid(self) -> None:
        for pair in ("BTC-USDC", "eth-usdc", "Sol-Usdc"):
            validate_pair(pair)

    def test_validate_pair_invalid(self) -> None:
        with pytest.raises(ValueError, match="Unsupported pair"):
            validate_pair("LINK-USDC")

    def test_validate_pair_malformed(self) -> None:
        with pytest.raises(ValueError, match="Unsupported pair"):
            validate_pair("BTCUSDC")

    def test_normalize_pair_to_hl(self) -> None:
        assert normalize_pair_to_hl("BTC-USDC") == "BTC"
        assert normalize_pair_to_hl("eth-usdc") == "ETH"

    def test_normalize_pair_to_vanta(self) -> None:
        assert normalize_pair_to_vanta("BTC-USDC") == "BTCUSD"
        assert normalize_pair_to_vanta("eth-usdc") == "ETHUSD"


# ── Input validation ─────────────────────────────────────────


class TestInputValidation:
    async def test_submit_invalid_pair(self, trading_client: HyperscaledClient) -> None:
        with pytest.raises(ValueError, match="Unsupported pair"):
            await trading_client.trade.submit_async(
                pair="LINK-USDC", side="long", size=Decimal("0.01"), order_type="market"
            )

    async def test_submit_invalid_side(self, trading_client: HyperscaledClient) -> None:
        with pytest.raises(ValueError, match="Invalid side"):
            await trading_client.trade.submit_async(
                pair="BTC-USDC", side="buy", size=Decimal("0.01"), order_type="market"
            )

    async def test_submit_zero_size(self, trading_client: HyperscaledClient) -> None:
        with pytest.raises(ValueError, match="Size must be positive"):
            await trading_client.trade.submit_async(
                pair="BTC-USDC", side="long", size=Decimal("0"), order_type="market"
            )

    async def test_submit_negative_size(self, trading_client: HyperscaledClient) -> None:
        with pytest.raises(ValueError, match="Size must be positive"):
            await trading_client.trade.submit_async(
                pair="BTC-USDC", side="long", size=Decimal("-1"), order_type="market"
            )

    async def test_submit_limit_missing_price(self, trading_client: HyperscaledClient) -> None:
        with pytest.raises(ValueError, match="Price is required for limit orders"):
            await trading_client.trade.submit_async(
                pair="BTC-USDC", side="long", size=Decimal("0.01"), order_type="limit"
            )

    async def test_submit_market_with_price(self, trading_client: HyperscaledClient) -> None:
        with pytest.raises(ValueError, match="Price must not be provided for market orders"):
            await trading_client.trade.submit_async(
                pair="BTC-USDC",
                side="long",
                size=Decimal("0.01"),
                order_type="market",
                price=Decimal("100000"),
            )


# ── Precondition checks ──────────────────────────────────────


class TestPreconditions:
    async def test_submit_no_funded_account_size(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        monkeypatch.setenv("HYPERSCALED_HL_PRIVATE_KEY", "0x" + "ab" * 32)
        client = HyperscaledClient()
        client.config.set_value("wallet.hl_address", VALID_ADDRESS)

        with pytest.raises(HyperscaledError, match="No funded account size configured"):
            await client.trade.submit_async(
                pair="BTC-USDC", side="long", size=Decimal("0.01"), order_type="market"
            )

    async def test_submit_no_private_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        monkeypatch.delenv("HYPERSCALED_HL_PRIVATE_KEY", raising=False)
        client = HyperscaledClient()
        client.config.set_value("wallet.hl_address", VALID_ADDRESS)
        client.config.set_value("account.funded_account_size", "100000")

        async def mock_balance(*_args: object, **_kwargs: object) -> BalanceStatus:
            return BalanceStatus(balance=Decimal("1000"), meets_minimum=True)

        client.account.check_balance_async = mock_balance  # type: ignore[assignment]

        with pytest.raises(HyperscaledError, match="No Hyperliquid private key"):
            await client.trade.submit_async(
                pair="BTC-USDC", side="long", size=Decimal("0.01"), order_type="market"
            )


# ── Successful submissions ───────────────────────────────────


class TestSubmitSuccess:
    async def test_submit_market_filled(self, trading_client: HyperscaledClient) -> None:
        mock_exchange = MagicMock()
        mock_exchange.market_open.return_value = _hl_filled_response()
        trading_client.trade._exchange = mock_exchange

        order = await trading_client.trade.submit_async(
            pair="BTC-USDC", side="long", size=Decimal("0.01"), order_type="market"
        )

        assert isinstance(order, Order)
        assert order.hl_order_id == "123456"
        assert order.pair == "BTC-USDC"
        assert order.side == "long"
        assert order.size == Decimal("0.01")
        assert order.order_type == "market"
        assert order.status == "filled"
        assert order.fill_price == Decimal("100250.50")
        assert order.scaling_ratio == Decimal("100000") / Decimal("1000")
        assert order.funded_equivalent_size == Decimal("0.01") * order.scaling_ratio
        mock_exchange.market_open.assert_called_once_with("BTC", True, 0.01)

    async def test_submit_market_partial(self, trading_client: HyperscaledClient) -> None:
        mock_exchange = MagicMock()
        mock_exchange.market_open.return_value = _hl_filled_response(total_sz="0.005")
        trading_client.trade._exchange = mock_exchange

        order = await trading_client.trade.submit_async(
            pair="BTC-USDC", side="long", size=Decimal("0.01"), order_type="market"
        )

        assert order.status == "partial"
        assert order.funded_equivalent_size == Decimal("0.005") * order.scaling_ratio

    async def test_submit_limit_pending(self, trading_client: HyperscaledClient) -> None:
        mock_exchange = MagicMock()
        mock_exchange.order.return_value = _hl_resting_response(oid=789)
        trading_client.trade._exchange = mock_exchange

        order = await trading_client.trade.submit_async(
            pair="ETH-USDC",
            side="short",
            size=Decimal("0.5"),
            order_type="limit",
            price=Decimal("3500.00"),
        )

        assert order.hl_order_id == "789"
        assert order.pair == "ETH-USDC"
        assert order.side == "short"
        assert order.order_type == "limit"
        assert order.status == "pending"
        assert order.fill_price is None
        assert order.funded_equivalent_size == Decimal("0.5") * order.scaling_ratio
        mock_exchange.order.assert_called_once_with(
            "ETH", False, 0.5, 3500.0, {"limit": {"tif": "Gtc"}}
        )

    async def test_submit_with_tp_sl(self, trading_client: HyperscaledClient) -> None:
        mock_exchange = MagicMock()
        mock_exchange.market_open.return_value = _hl_filled_response()
        trading_client.trade._exchange = mock_exchange

        order = await trading_client.trade.submit_async(
            pair="BTC-USDC",
            side="long",
            size=Decimal("0.01"),
            order_type="market",
            take_profit=Decimal("110000"),
            stop_loss=Decimal("95000"),
        )

        assert order.take_profit == Decimal("110000")
        assert order.stop_loss == Decimal("95000")


# ── Scaling ratio computation ─────────────────────────────────


class TestScalingRatio:
    async def test_scaling_ratio_computation(self, trading_client: HyperscaledClient) -> None:
        mock_exchange = MagicMock()
        mock_exchange.market_open.return_value = _hl_filled_response(total_sz="0.02")
        trading_client.trade._exchange = mock_exchange

        order = await trading_client.trade.submit_async(
            pair="BTC-USDC", side="long", size=Decimal("0.02"), order_type="market"
        )

        expected_ratio = Decimal("100000") / Decimal("1000")
        assert order.scaling_ratio == expected_ratio
        assert order.funded_equivalent_size == Decimal("0.02") * expected_ratio

    async def test_scaling_ratio_different_balance(
        self, trading_client: HyperscaledClient
    ) -> None:
        async def balance_5000(*_args: object, **_kwargs: object) -> BalanceStatus:
            return BalanceStatus(balance=Decimal("5000"), meets_minimum=True)

        trading_client.account.check_balance_async = balance_5000  # type: ignore[assignment]

        mock_exchange = MagicMock()
        mock_exchange.market_open.return_value = _hl_filled_response(total_sz="0.1")
        trading_client.trade._exchange = mock_exchange

        order = await trading_client.trade.submit_async(
            pair="SOL-USDC", side="short", size=Decimal("0.1"), order_type="market"
        )

        expected_ratio = Decimal("100000") / Decimal("5000")
        assert order.scaling_ratio == expected_ratio
        assert order.funded_equivalent_size == Decimal("0.1") * expected_ratio


# ── Error paths ───────────────────────────────────────────────


class TestErrorPaths:
    async def test_submit_hl_rejection(self, trading_client: HyperscaledClient) -> None:
        mock_exchange = MagicMock()
        mock_exchange.market_open.return_value = _hl_error_response("Insufficient margin")
        trading_client.trade._exchange = mock_exchange

        with pytest.raises(HyperscaledError, match="Order rejected.*Insufficient margin"):
            await trading_client.trade.submit_async(
                pair="BTC-USDC", side="long", size=Decimal("0.01"), order_type="market"
            )

    async def test_submit_hl_transport_failure(self, trading_client: HyperscaledClient) -> None:
        mock_exchange = MagicMock()
        mock_exchange.market_open.side_effect = ConnectionError("timeout")
        trading_client.trade._exchange = mock_exchange

        with pytest.raises(HyperscaledError, match="order submission failed"):
            await trading_client.trade.submit_async(
                pair="BTC-USDC", side="long", size=Decimal("0.01"), order_type="market"
            )

    async def test_submit_hl_top_level_failure(self, trading_client: HyperscaledClient) -> None:
        mock_exchange = MagicMock()
        mock_exchange.market_open.return_value = _hl_top_level_failure()
        trading_client.trade._exchange = mock_exchange

        with pytest.raises(HyperscaledError, match="Hyperliquid order failed"):
            await trading_client.trade.submit_async(
                pair="BTC-USDC", side="long", size=Decimal("0.01"), order_type="market"
            )

    async def test_submit_hl_unexpected_response(
        self, trading_client: HyperscaledClient
    ) -> None:
        mock_exchange = MagicMock()
        mock_exchange.market_open.return_value = {"status": "ok", "response": {}}
        trading_client.trade._exchange = mock_exchange

        with pytest.raises(HyperscaledError, match="Unexpected Hyperliquid response"):
            await trading_client.trade.submit_async(
                pair="BTC-USDC", side="long", size=Decimal("0.01"), order_type="market"
            )

    async def test_submit_hl_unexpected_status_entry(
        self, trading_client: HyperscaledClient
    ) -> None:
        mock_exchange = MagicMock()
        mock_exchange.market_open.return_value = {
            "status": "ok",
            "response": {"data": {"statuses": [{"unknown_key": 42}]}},
        }
        trading_client.trade._exchange = mock_exchange

        with pytest.raises(HyperscaledError, match="Unexpected"):
            await trading_client.trade.submit_async(
                pair="BTC-USDC", side="long", size=Decimal("0.01"), order_type="market"
            )

    async def test_submit_zero_balance(self, trading_client: HyperscaledClient) -> None:
        async def zero_balance(*_args: object, **_kwargs: object) -> BalanceStatus:
            return BalanceStatus(balance=Decimal("0"), meets_minimum=False)

        trading_client.account.check_balance_async = zero_balance  # type: ignore[assignment]

        with pytest.raises(HyperscaledError, match="balance is zero or negative"):
            await trading_client.trade.submit_async(
                pair="BTC-USDC", side="long", size=Decimal("0.01"), order_type="market"
            )


# ── Pre-validate seam ────────────────────────────────────────


class TestPreValidateSeam:
    async def test_pre_validate_called(self, trading_client: HyperscaledClient) -> None:
        call_log: list[tuple[str, ...]] = []

        async def track_pre_validate(
            pair: str, side: str, size: object, order_type: str, price: object
        ) -> None:
            call_log.append((pair, side, order_type))

        trading_client.trade._pre_validate = track_pre_validate  # type: ignore[assignment]

        mock_exchange = MagicMock()
        mock_exchange.market_open.return_value = _hl_filled_response()
        trading_client.trade._exchange = mock_exchange

        await trading_client.trade.submit_async(
            pair="BTC-USDC", side="long", size=Decimal("0.01"), order_type="market"
        )

        assert len(call_log) == 1
        assert call_log[0] == ("BTC-USDC", "long", "market")
