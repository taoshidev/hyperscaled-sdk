"""Tests for SDK-TP-SL — TP/SL and Trailing Stop Loss."""

from __future__ import annotations

import time
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hyperscaled.exceptions import HyperscaledError
from hyperscaled.models.account import BalanceStatus
from hyperscaled.models.rules import TradeValidation
from hyperscaled.models.trading import Order
from hyperscaled.sdk.client import HyperscaledClient
from hyperscaled.sdk.trading import TradingClient

VALID_ADDRESS = "0x" + "a1" * 20

# Fixed timestamp for deterministic OID resolution in tests.
# _parse_trigger_response calls time.time() to get placement_ts, and
# _resolve_trigger_oids_from_frontend filters by recency relative to that.
# Tests that go through the full trigger placement flow patch time.time to
# return _FIXED_TS so fixture timestamps are always in the recency window.
_FIXED_TS = 1800000000.0  # a fixed point in 2027
_FIXED_TS_MS = int(_FIXED_TS * 1000)


# ── Response helpers ──────────────────────────────────────────


def _hl_filled_response(
    oid: int = 123456,
    total_sz: str = "0.01",
    avg_px: str = "67946.0",
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
            "data": {"statuses": [{"resting": {"oid": oid}}]},
        },
    }


def _hl_trigger_resting_response(oid: int = 999001) -> dict:
    return {
        "status": "ok",
        "response": {
            "type": "order",
            "data": {"statuses": [{"resting": {"oid": oid}}]},
        },
    }


def _hl_grouped_trigger_response() -> dict:
    """positionTpsl bulk_orders: bare 'waitingForTrigger' strings."""
    return {
        "status": "ok",
        "response": {
            "type": "order",
            "data": {"statuses": ["waitingForTrigger", "waitingForTrigger"]},
        },
    }


def _hl_trigger_error_response(error: str = "Invalid TP/SL price. asset=0") -> dict:
    return {
        "status": "ok",
        "response": {
            "type": "order",
            "data": {"statuses": [{"error": error}]},
        },
    }


def _hl_cancel_response(*statuses: object) -> dict:
    return {
        "status": "ok",
        "response": {
            "type": "cancel",
            "data": {"statuses": list(statuses)},
        },
    }


def _frontend_open_orders_tp_sl(
    coin: str = "BTC",
    tp_oid: int = 366829521459,
    sl_oid: int = 366829521460,
    tp_px: str = "74741.0",
    sl_px: str = "61151.0",
    sz: str = "0.0002",
    timestamp: int | None = None,
) -> list[dict]:
    """Spike-derived frontend_open_orders payload for grouped TP+SL."""
    if timestamp is None:
        timestamp = _FIXED_TS_MS + 500
    return [
        {
            "coin": coin,
            "side": "A",
            "limitPx": sl_px,
            "sz": sz,
            "oid": sl_oid,
            "timestamp": timestamp,
            "triggerCondition": f"Price below {sl_px.split('.')[0]}",
            "isTrigger": True,
            "triggerPx": sl_px,
            "children": [],
            "isPositionTpsl": False,
            "reduceOnly": True,
            "orderType": "Stop Market",
            "origSz": sz,
            "tif": None,
            "cloid": None,
        },
        {
            "coin": coin,
            "side": "A",
            "limitPx": tp_px,
            "sz": sz,
            "oid": tp_oid,
            "timestamp": timestamp,
            "triggerCondition": f"Price above {tp_px.split('.')[0]}",
            "isTrigger": True,
            "triggerPx": tp_px,
            "children": [],
            "isPositionTpsl": False,
            "reduceOnly": True,
            "orderType": "Take Profit Market",
            "origSz": sz,
            "tif": None,
            "cloid": None,
        },
    ]


def _clearinghouse_with_position(
    coin: str = "BTC", szi: str = "0.01", entry_px: str = "67946.0"
) -> dict:
    return {
        "assetPositions": [
            {
                "position": {
                    "coin": coin,
                    "szi": szi,
                    "entryPx": entry_px,
                    "positionValue": str(float(szi) * float(entry_px)),
                }
            }
        ]
    }


# ── Fixtures ──────────────────────────────────────────────────


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
    client.rules = MagicMock()
    client.rules.validate_trade_async = AsyncMock(
        return_value=TradeValidation(valid=True, violations=[])
    )

    return client


# ── Validation tests ──────────────────────────────────────────


class TestTrailingStopValidation:
    def test_trailing_stop_validation_both(self) -> None:
        with pytest.raises(ValueError, match="exactly one of"):
            TradingClient._validate_trailing_stop(
                {"trailing_percent": 0.02, "trailing_value": 500}
            )

    def test_trailing_stop_validation_neither(self) -> None:
        with pytest.raises(ValueError, match="exactly one of"):
            TradingClient._validate_trailing_stop({})

    def test_trailing_stop_validation_percent_range_zero(self) -> None:
        with pytest.raises(ValueError, match="between 0 and 1"):
            TradingClient._validate_trailing_stop({"trailing_percent": 0})

    def test_trailing_stop_validation_percent_range_one(self) -> None:
        with pytest.raises(ValueError, match="between 0 and 1"):
            TradingClient._validate_trailing_stop({"trailing_percent": 1.0})

    def test_trailing_stop_validation_percent_range_negative(self) -> None:
        with pytest.raises(ValueError, match="between 0 and 1"):
            TradingClient._validate_trailing_stop({"trailing_percent": -0.1})

    def test_trailing_stop_validation_value_negative(self) -> None:
        with pytest.raises(ValueError, match="greater than 0"):
            TradingClient._validate_trailing_stop({"trailing_value": -100})

    def test_trailing_stop_validation_value_zero(self) -> None:
        with pytest.raises(ValueError, match="greater than 0"):
            TradingClient._validate_trailing_stop({"trailing_value": 0})

    def test_trailing_stop_validation_valid_percent(self) -> None:
        TradingClient._validate_trailing_stop({"trailing_percent": 0.05})

    def test_trailing_stop_validation_valid_value(self) -> None:
        TradingClient._validate_trailing_stop({"trailing_value": 500})


class TestTpSlPriceValidation:
    def test_tp_sl_validation_long_sl_above_entry(self) -> None:
        with pytest.raises(ValueError, match="LONG stop_loss.*must be below"):
            TradingClient._validate_tp_sl_prices(
                "long", None, Decimal("70000"), Decimal("67946")
            )

    def test_tp_sl_validation_long_sl_equal_entry(self) -> None:
        with pytest.raises(ValueError, match="LONG stop_loss.*must be below"):
            TradingClient._validate_tp_sl_prices(
                "long", None, Decimal("67946"), Decimal("67946")
            )

    def test_tp_sl_validation_long_tp_below_entry(self) -> None:
        with pytest.raises(ValueError, match="LONG take_profit.*must be above"):
            TradingClient._validate_tp_sl_prices(
                "long", Decimal("60000"), None, Decimal("67946")
            )

    def test_tp_sl_validation_short_sl_below_entry(self) -> None:
        with pytest.raises(ValueError, match="SHORT stop_loss.*must be above"):
            TradingClient._validate_tp_sl_prices(
                "short", None, Decimal("60000"), Decimal("67946")
            )

    def test_tp_sl_validation_short_tp_above_entry(self) -> None:
        with pytest.raises(ValueError, match="SHORT take_profit.*must be below"):
            TradingClient._validate_tp_sl_prices(
                "short", Decimal("70000"), None, Decimal("67946")
            )

    def test_tp_sl_validation_long_valid(self) -> None:
        TradingClient._validate_tp_sl_prices(
            "long", Decimal("75000"), Decimal("60000"), Decimal("67946")
        )

    def test_tp_sl_validation_short_valid(self) -> None:
        TradingClient._validate_tp_sl_prices(
            "short", Decimal("60000"), Decimal("75000"), Decimal("67946")
        )


# ── Trailing stop computation ─────────────────────────────────


class TestComputeTrailingSl:
    def test_compute_trailing_sl_long_percent(self) -> None:
        sl = TradingClient._compute_trailing_sl(
            "long", Decimal("100000"), {"trailing_percent": 0.02}
        )
        assert sl == Decimal("100000") * Decimal("0.98")

    def test_compute_trailing_sl_short_percent(self) -> None:
        sl = TradingClient._compute_trailing_sl(
            "short", Decimal("100000"), {"trailing_percent": 0.02}
        )
        assert sl == Decimal("100000") * Decimal("1.02")

    def test_compute_trailing_sl_long_value(self) -> None:
        sl = TradingClient._compute_trailing_sl(
            "long", Decimal("100000"), {"trailing_value": 2000}
        )
        assert sl == Decimal("98000")

    def test_compute_trailing_sl_short_value(self) -> None:
        sl = TradingClient._compute_trailing_sl(
            "short", Decimal("100000"), {"trailing_value": 2000}
        )
        assert sl == Decimal("102000")

    def test_compute_trailing_sl_merges_fixed_long_trailing_more_protective(self) -> None:
        # trailing_sl = 98000, fixed_sl = 95000 → use 98000 (more protective for LONG)
        sl = TradingClient._compute_trailing_sl(
            "long",
            Decimal("100000"),
            {"trailing_value": 2000},
            fixed_sl=Decimal("95000"),
        )
        assert sl == Decimal("98000")

    def test_compute_trailing_sl_merges_fixed_long_fixed_more_protective(self) -> None:
        # trailing_sl = 98000, fixed_sl = 99000 → use 99000 (more protective for LONG)
        sl = TradingClient._compute_trailing_sl(
            "long",
            Decimal("100000"),
            {"trailing_value": 2000},
            fixed_sl=Decimal("99000"),
        )
        assert sl == Decimal("99000")

    def test_compute_trailing_sl_merges_fixed_short(self) -> None:
        # trailing_sl = 102000, fixed_sl = 105000 → use 102000 (more protective for SHORT)
        sl = TradingClient._compute_trailing_sl(
            "short",
            Decimal("100000"),
            {"trailing_value": 2000},
            fixed_sl=Decimal("105000"),
        )
        assert sl == Decimal("102000")


# ── Trigger price rounding ────────────────────────────────────


class TestTriggerPriceRounding:
    def test_trigger_price_rounding_integer_btc(self) -> None:
        client = TradingClient.__new__(TradingClient)
        result = client._round_trigger_price("BTC", Decimal("81507.6"))
        assert result == Decimal("81508")

    @pytest.mark.parametrize(
        ("asset", "input_price", "expected"),
        [
            ("BTC", Decimal("67946.4"), Decimal("67946")),
            ("BTC", Decimal("67946.5"), Decimal("67947")),
            ("ETH", Decimal("3456.78"), Decimal("3456.8")),
            ("SOL", Decimal("145.678"), Decimal("145.68")),
            ("XRP", Decimal("0.54321"), Decimal("0.5432")),
            ("DOGE", Decimal("0.123456"), Decimal("0.12346")),
            ("ADA", Decimal("0.45678"), Decimal("0.4568")),
        ],
    )
    def test_trigger_price_quantization_all_pairs(
        self, asset: str, input_price: Decimal, expected: Decimal
    ) -> None:
        client = TradingClient.__new__(TradingClient)
        assert client._round_trigger_price(asset, input_price) == expected

    def test_trigger_price_rounding_unknown_asset_raises(self) -> None:
        client = TradingClient.__new__(TradingClient)
        with pytest.raises(HyperscaledError, match="No trigger price precision"):
            client._round_trigger_price("LINK", Decimal("15.50"))

    def test_trigger_price_rounding_per_asset(self) -> None:
        client = TradingClient.__new__(TradingClient)
        for asset, decimals in TradingClient.TRIGGER_PRICE_DECIMALS.items():
            result = client._round_trigger_price(asset, Decimal("12345.6789012345"))
            if decimals == 0:
                assert result == result.to_integral_value()
            else:
                assert abs(result.as_tuple().exponent) <= decimals  # type: ignore[operator]


# ── Submit with TP/SL triggers ────────────────────────────────


class TestSubmitWithTpSl:
    @patch("hyperscaled.sdk.trading.time.time", return_value=_FIXED_TS)
    async def test_submit_market_with_tp_sl(
        self, _mock_time: MagicMock, trading_client: HyperscaledClient
    ) -> None:
        mock_exchange = MagicMock()
        mock_exchange.market_open.return_value = _hl_filled_response()
        mock_exchange.bulk_orders.return_value = _hl_grouped_trigger_response()
        trading_client.trade._exchange = mock_exchange

        mock_info = MagicMock()
        mock_info.frontend_open_orders.return_value = _frontend_open_orders_tp_sl(
            tp_px="74741.0", sl_px="61151.0", sz="0.01",
        )
        trading_client.trade._info = mock_info

        order = await trading_client.trade.submit_async(
            pair="BTC-USDC",
            side="long",
            size=Decimal("0.01"),
            order_type="market",
            take_profit=Decimal("74741"),
            stop_loss=Decimal("61151"),
        )

        assert order.status == "filled"
        assert order.tp_order_id is not None
        assert order.sl_order_id is not None
        assert order.trigger_status == "placed"
        assert order.trigger_error is None
        mock_exchange.bulk_orders.assert_called_once()
        args = mock_exchange.bulk_orders.call_args
        assert args[0][2] == "positionTpsl"

    async def test_submit_market_tp_only(
        self, trading_client: HyperscaledClient
    ) -> None:
        mock_exchange = MagicMock()
        mock_exchange.market_open.return_value = _hl_filled_response()
        mock_exchange.order.return_value = _hl_trigger_resting_response(oid=999001)
        trading_client.trade._exchange = mock_exchange

        order = await trading_client.trade.submit_async(
            pair="BTC-USDC",
            side="long",
            size=Decimal("0.01"),
            order_type="market",
            take_profit=Decimal("74741"),
        )

        assert order.tp_order_id == "999001"
        assert order.sl_order_id is None
        assert order.trigger_status == "placed"
        # Single trigger uses exchange.order, not bulk_orders
        mock_exchange.bulk_orders.assert_not_called()

    async def test_submit_market_sl_only(
        self, trading_client: HyperscaledClient
    ) -> None:
        mock_exchange = MagicMock()
        mock_exchange.market_open.return_value = _hl_filled_response()
        mock_exchange.order.return_value = _hl_trigger_resting_response(oid=999002)
        trading_client.trade._exchange = mock_exchange

        order = await trading_client.trade.submit_async(
            pair="BTC-USDC",
            side="long",
            size=Decimal("0.01"),
            order_type="market",
            stop_loss=Decimal("61151"),
        )

        assert order.tp_order_id is None
        assert order.sl_order_id == "999002"
        assert order.trigger_status == "placed"

    async def test_submit_market_trailing_sl(
        self, trading_client: HyperscaledClient
    ) -> None:
        mock_exchange = MagicMock()
        mock_exchange.market_open.return_value = _hl_filled_response(
            avg_px="100000.0"
        )
        mock_exchange.order.return_value = _hl_trigger_resting_response(oid=999003)
        trading_client.trade._exchange = mock_exchange

        order = await trading_client.trade.submit_async(
            pair="BTC-USDC",
            side="long",
            size=Decimal("0.01"),
            order_type="market",
            trailing_stop={"trailing_percent": 0.02},
        )

        assert order.sl_order_id == "999003"
        assert order.trailing_stop == {"trailing_percent": 0.02}
        assert order.trigger_status == "placed"
        # SL should be at fill * (1 - 0.02) = 98000
        assert order.stop_loss == Decimal("100000.0") * Decimal("0.98")

    async def test_submit_market_trailing_and_fixed_sl(
        self, trading_client: HyperscaledClient
    ) -> None:
        mock_exchange = MagicMock()
        mock_exchange.market_open.return_value = _hl_filled_response(
            avg_px="100000.0"
        )
        mock_exchange.order.return_value = _hl_trigger_resting_response(oid=999004)
        trading_client.trade._exchange = mock_exchange

        order = await trading_client.trade.submit_async(
            pair="BTC-USDC",
            side="long",
            size=Decimal("0.01"),
            order_type="market",
            stop_loss=Decimal("99000"),
            trailing_stop={"trailing_value": 2000},
        )

        # trailing_sl = 98000, fixed_sl = 99000 → use 99000 (more protective)
        assert order.stop_loss == Decimal("99000")
        assert order.sl_order_id == "999004"

    async def test_submit_partial_fill_uses_filled_size(
        self, trading_client: HyperscaledClient
    ) -> None:
        mock_exchange = MagicMock()
        mock_exchange.market_open.return_value = _hl_filled_response(
            total_sz="0.005"
        )
        mock_exchange.order.return_value = _hl_trigger_resting_response(oid=999005)
        trading_client.trade._exchange = mock_exchange

        order = await trading_client.trade.submit_async(
            pair="BTC-USDC",
            side="long",
            size=Decimal("0.01"),
            order_type="market",
            stop_loss=Decimal("61151"),
        )

        assert order.status == "partial"
        assert order.filled_size == Decimal("0.005")
        # Trigger should use filled_size (0.005), not requested size (0.01)
        call_args = mock_exchange.order.call_args
        assert call_args[0][2] == 0.005  # sz argument

    async def test_submit_limit_pending_no_triggers(
        self, trading_client: HyperscaledClient
    ) -> None:
        mock_exchange = MagicMock()
        mock_exchange.order.return_value = _hl_resting_response(oid=789)
        trading_client.trade._exchange = mock_exchange

        order = await trading_client.trade.submit_async(
            pair="ETH-USDC",
            side="short",
            size=Decimal("0.5"),
            order_type="limit",
            price=Decimal("3500.00"),
            take_profit=Decimal("3200"),
            stop_loss=Decimal("3800"),
        )

        assert order.status == "pending"
        assert order.take_profit == Decimal("3200")
        assert order.stop_loss == Decimal("3800")
        assert order.tp_order_id is None
        assert order.sl_order_id is None
        assert order.trigger_status == "pending_parent_fill"

    async def test_submit_tp_sl_failure_returns_order(
        self, trading_client: HyperscaledClient
    ) -> None:
        mock_exchange = MagicMock()
        mock_exchange.market_open.return_value = _hl_filled_response()
        mock_exchange.order.side_effect = ConnectionError("trigger placement timeout")
        trading_client.trade._exchange = mock_exchange

        order = await trading_client.trade.submit_async(
            pair="BTC-USDC",
            side="long",
            size=Decimal("0.01"),
            order_type="market",
            stop_loss=Decimal("61151"),
        )

        # Parent order should still be returned
        assert order.status == "filled"
        assert order.hl_order_id == "123456"
        assert order.tp_order_id is None
        assert order.sl_order_id is None

    async def test_submit_tp_sl_failure_sets_trigger_status(
        self, trading_client: HyperscaledClient
    ) -> None:
        mock_exchange = MagicMock()
        mock_exchange.market_open.return_value = _hl_filled_response()
        mock_exchange.order.return_value = _hl_trigger_error_response(
            "Insufficient margin"
        )
        trading_client.trade._exchange = mock_exchange

        order = await trading_client.trade.submit_async(
            pair="BTC-USDC",
            side="long",
            size=Decimal("0.01"),
            order_type="market",
            stop_loss=Decimal("61151"),
        )

        assert order.trigger_status == "failed"
        assert order.trigger_error is not None
        assert "Insufficient margin" in order.trigger_error

    @patch("hyperscaled.sdk.trading.time.time", return_value=_FIXED_TS)
    async def test_submit_tp_sl_partial_failure_sets_status(
        self, _mock_time: MagicMock, trading_client: HyperscaledClient
    ) -> None:
        mock_exchange = MagicMock()
        mock_exchange.market_open.return_value = _hl_filled_response()
        # One resting + one error
        mock_exchange.bulk_orders.return_value = {
            "status": "ok",
            "response": {
                "type": "order",
                "data": {
                    "statuses": [
                        {"resting": {"oid": 999010}},
                        {"error": "SL price invalid"},
                    ]
                },
            },
        }
        trading_client.trade._exchange = mock_exchange

        order = await trading_client.trade.submit_async(
            pair="BTC-USDC",
            side="long",
            size=Decimal("0.01"),
            order_type="market",
            take_profit=Decimal("74741"),
            stop_loss=Decimal("61151"),
        )

        assert order.trigger_status == "partial_failure"
        assert order.tp_order_id == "999010"
        assert order.sl_order_id is None
        assert "SL price invalid" in (order.trigger_error or "")


# ── Grouped placement and OID resolution ──────────────────────


class TestGroupedPlacement:
    @patch("hyperscaled.sdk.trading.time.time", return_value=_FIXED_TS)
    async def test_positionTpsl_grouping(
        self, _mock_time: MagicMock, trading_client: HyperscaledClient
    ) -> None:
        mock_exchange = MagicMock()
        mock_exchange.market_open.return_value = _hl_filled_response()
        mock_exchange.bulk_orders.return_value = _hl_grouped_trigger_response()
        trading_client.trade._exchange = mock_exchange

        mock_info = MagicMock()
        mock_info.frontend_open_orders.return_value = _frontend_open_orders_tp_sl(
            sz="0.01"
        )
        trading_client.trade._info = mock_info

        order = await trading_client.trade.submit_async(
            pair="BTC-USDC",
            side="long",
            size=Decimal("0.01"),
            order_type="market",
            take_profit=Decimal("74741"),
            stop_loss=Decimal("61151"),
        )

        mock_exchange.bulk_orders.assert_called_once()
        args = mock_exchange.bulk_orders.call_args
        assert args[0][2] == "positionTpsl"
        assert order.trigger_status == "placed"

    async def test_single_trigger_order_path(
        self, trading_client: HyperscaledClient
    ) -> None:
        mock_exchange = MagicMock()
        mock_exchange.market_open.return_value = _hl_filled_response()
        mock_exchange.order.return_value = _hl_trigger_resting_response(oid=888)
        trading_client.trade._exchange = mock_exchange

        order = await trading_client.trade.submit_async(
            pair="BTC-USDC",
            side="long",
            size=Decimal("0.01"),
            order_type="market",
            take_profit=Decimal("74741"),
        )

        assert order.tp_order_id == "888"
        # Single trigger should use exchange.order(), not bulk_orders
        mock_exchange.bulk_orders.assert_not_called()
        assert mock_exchange.order.called

    @patch("hyperscaled.sdk.trading.time.time", return_value=_FIXED_TS)
    async def test_grouped_placement_returns_waiting_for_trigger(
        self, _mock_time: MagicMock, trading_client: HyperscaledClient
    ) -> None:
        """Spike-derived: positionTpsl returns 'waitingForTrigger' strings."""
        mock_exchange = MagicMock()
        mock_exchange.market_open.return_value = _hl_filled_response()
        mock_exchange.bulk_orders.return_value = _hl_grouped_trigger_response()
        trading_client.trade._exchange = mock_exchange

        mock_info = MagicMock()
        mock_info.frontend_open_orders.return_value = _frontend_open_orders_tp_sl(
            sz="0.01"
        )
        trading_client.trade._info = mock_info

        order = await trading_client.trade.submit_async(
            pair="BTC-USDC",
            side="long",
            size=Decimal("0.01"),
            order_type="market",
            take_profit=Decimal("74741"),
            stop_loss=Decimal("61151"),
        )

        assert order.tp_order_id is not None
        assert order.sl_order_id is not None
        mock_info.frontend_open_orders.assert_called()

    @patch("hyperscaled.sdk.trading.time.time", return_value=_FIXED_TS)
    async def test_grouped_oid_resolution_via_frontend_open_orders(
        self, _mock_time: MagicMock, trading_client: HyperscaledClient
    ) -> None:
        """Spike-derived: OIDs resolved from frontend_open_orders using multi-field matching."""
        mock_exchange = MagicMock()
        mock_exchange.market_open.return_value = _hl_filled_response()
        mock_exchange.bulk_orders.return_value = _hl_grouped_trigger_response()
        trading_client.trade._exchange = mock_exchange

        tp_oid = 11111
        sl_oid = 22222
        mock_info = MagicMock()
        mock_info.frontend_open_orders.return_value = _frontend_open_orders_tp_sl(
            tp_oid=tp_oid, sl_oid=sl_oid, sz="0.01",
        )
        trading_client.trade._info = mock_info

        order = await trading_client.trade.submit_async(
            pair="BTC-USDC",
            side="long",
            size=Decimal("0.01"),
            order_type="market",
            take_profit=Decimal("74741"),
            stop_loss=Decimal("61151"),
        )

        assert order.tp_order_id == str(tp_oid)
        assert order.sl_order_id == str(sl_oid)


# ── OID resolution edge cases ─────────────────────────────────


class TestResolveOids:
    async def test_resolve_oids_retry_on_miss(
        self, trading_client: HyperscaledClient
    ) -> None:
        """Retry loop in _parse_trigger_response retries up to 3 times."""
        resolve_calls = 0

        async def mock_resolve(*args, **kwargs):
            nonlocal resolve_calls
            resolve_calls += 1
            if resolve_calls < 3:
                return None, None
            return "tp_oid_found", "sl_oid_found"

        trading_client.trade._resolve_trigger_oids_from_frontend = mock_resolve  # type: ignore[assignment]

        result = _hl_grouped_trigger_response()
        with patch("hyperscaled.sdk.trading.asyncio.sleep", new_callable=AsyncMock):
            tp_oid, sl_oid, status, error = await trading_client.trade._parse_trigger_response(
                result, tp_idx=0, sl_idx=1, is_grouped=True,
                hl_name="BTC", tp_px=74741.0, sl_px=61151.0, filled_sz=0.01,
                pre_placement_ts_ms=_FIXED_TS_MS,
            )

        assert resolve_calls == 3
        assert tp_oid == "tp_oid_found"
        assert sl_oid == "sl_oid_found"
        assert status == "placed"

    async def test_resolve_oids_recency_filter(
        self, trading_client: HyperscaledClient
    ) -> None:
        """Stale trigger orders outside recency window are not matched."""
        now_ms = int(time.time() * 1000)
        mock_info = MagicMock()
        stale_orders = _frontend_open_orders_tp_sl(
            timestamp=now_ms - 60_000, sz="0.01",
        )
        mock_info.frontend_open_orders.return_value = stale_orders
        trading_client.trade._info = mock_info

        tp_oid, sl_oid = await trading_client.trade._resolve_trigger_oids_from_frontend(
            "BTC", 74741.0, 61151.0, 0.01, now_ms,
        )

        assert tp_oid is None
        assert sl_oid is None

    async def test_resolve_oids_exact_timestamp_grouping(
        self, trading_client: HyperscaledClient
    ) -> None:
        """When both TP and SL candidates exist, prefer pair sharing same timestamp."""
        now_ms = int(time.time() * 1000)
        ts = now_ms + 500
        mock_info = MagicMock()
        orders = _frontend_open_orders_tp_sl(
            tp_oid=111, sl_oid=222, timestamp=ts, sz="0.01",
        )
        # Add a stale TP candidate with different timestamp (but within window)
        stale_tp = dict(orders[1])
        stale_tp["oid"] = 333
        stale_tp["timestamp"] = ts + 1
        orders.append(stale_tp)

        mock_info.frontend_open_orders.return_value = orders
        trading_client.trade._info = mock_info

        tp_oid, sl_oid = await trading_client.trade._resolve_trigger_oids_from_frontend(
            "BTC", 74741.0, 61151.0, 0.01, now_ms,
        )

        # Should prefer the pair sharing the same timestamp
        assert tp_oid == "111"
        assert sl_oid == "222"

    async def test_resolve_oids_string_comparison(
        self, trading_client: HyperscaledClient
    ) -> None:
        """triggerPx and sz are compared as strings."""
        now_ms = int(time.time() * 1000)
        ts = now_ms + 500
        mock_info = MagicMock()
        orders = _frontend_open_orders_tp_sl(
            tp_px="74741.0", sl_px="61151.0", sz="0.01", timestamp=ts,
        )
        mock_info.frontend_open_orders.return_value = orders
        trading_client.trade._info = mock_info

        tp_oid, sl_oid = await trading_client.trade._resolve_trigger_oids_from_frontend(
            "BTC", 74741.0, 61151.0, 0.01, now_ms,
        )

        assert tp_oid is not None
        assert sl_oid is not None

    async def test_is_position_tpsl_not_relied_upon(
        self, trading_client: HyperscaledClient
    ) -> None:
        """Spike-derived: isPositionTpsl is always false, not used for identification."""
        now_ms = int(time.time() * 1000)
        ts = now_ms + 500
        mock_info = MagicMock()
        orders = _frontend_open_orders_tp_sl(timestamp=ts, sz="0.01")
        for o in orders:
            assert o["isPositionTpsl"] is False

        mock_info.frontend_open_orders.return_value = orders
        trading_client.trade._info = mock_info

        tp_oid, sl_oid = await trading_client.trade._resolve_trigger_oids_from_frontend(
            "BTC", 74741.0, 61151.0, 0.01, now_ms,
        )

        assert tp_oid is not None
        assert sl_oid is not None

    async def test_exchange_timestamp_within_backwards_buffer_matches(
        self, trading_client: HyperscaledClient
    ) -> None:
        """_place_tp_sl_triggers records pre_placement_ts as
        (local_clock - 2s buffer) before calling the exchange. The exchange
        assigns its own timestamp when it receives the request. This test
        verifies that an exchange timestamp 100ms after pre_placement_ts is
        found — simulating the common case where the exchange timestamp
        falls between (local_clock - 2s) and local_clock.
        """
        pre_placement_ts = 1800000000000  # ms
        exchange_ts = pre_placement_ts + 100  # 100ms after the buffered ts
        mock_info = MagicMock()
        orders = _frontend_open_orders_tp_sl(
            tp_oid=111, sl_oid=222, timestamp=exchange_ts, sz="0.01",
        )
        mock_info.frontend_open_orders.return_value = orders
        trading_client.trade._info = mock_info

        tp_oid, sl_oid = await trading_client.trade._resolve_trigger_oids_from_frontend(
            "BTC", 74741.0, 61151.0, 0.01, pre_placement_ts,
        )

        assert tp_oid == "111"
        assert sl_oid == "222"

    async def test_frontend_open_orders_trigger_fields(
        self, trading_client: HyperscaledClient
    ) -> None:
        """Spike-derived: payload includes all trigger identification fields."""
        orders = _frontend_open_orders_tp_sl()
        for order in orders:
            assert "isTrigger" in order
            assert "triggerPx" in order
            assert "triggerCondition" in order
            assert "orderType" in order
            assert "reduceOnly" in order
            assert "sz" in order
            assert order["isTrigger"] is True
            assert order["reduceOnly"] is True


# ── set_tp_sl ─────────────────────────────────────────────────


class TestSetTpSl:
    @patch("hyperscaled.sdk.trading.time.time", return_value=_FIXED_TS)
    async def test_set_tp_sl_on_existing_position(
        self, _mock_time: MagicMock, trading_client: HyperscaledClient
    ) -> None:
        mock_exchange = MagicMock()
        mock_exchange.bulk_cancel.return_value = _hl_cancel_response("success", "success")
        mock_exchange.bulk_orders.return_value = _hl_grouped_trigger_response()
        trading_client.trade._exchange = mock_exchange

        mock_info = MagicMock()
        # First call: find existing triggers
        existing_triggers = _frontend_open_orders_tp_sl(sz="0.01")
        # Second call: resolve new OIDs
        new_triggers = _frontend_open_orders_tp_sl(
            tp_oid=55555, sl_oid=66666, tp_px="80000.0", sl_px="50000.0", sz="0.01",
        )
        mock_info.frontend_open_orders.side_effect = [
            existing_triggers,
            new_triggers,
        ]
        trading_client.trade._info = mock_info

        mock_response = MagicMock()
        mock_response.json.return_value = _clearinghouse_with_position()
        mock_response.raise_for_status = MagicMock()

        async def mock_post(url: str, json: dict) -> MagicMock:
            if json.get("type") == "clearinghouseState":
                return mock_response
            if json.get("type") == "allMids":
                mid_resp = MagicMock()
                mid_resp.json.return_value = {"BTC": "67946.0"}
                mid_resp.raise_for_status = MagicMock()
                return mid_resp
            return mock_response

        trading_client.trade._client.http.post = mock_post  # type: ignore[assignment]

        result = await trading_client.trade.set_tp_sl_async(
            pair="BTC-USDC",
            take_profit=Decimal("80000"),
            stop_loss=Decimal("50000"),
        )

        assert result["tp_order_id"] is not None
        assert result["sl_order_id"] is not None
        assert result["trigger_status"] == "placed"
        mock_exchange.bulk_cancel.assert_called_once()

    async def test_set_tp_sl_no_position(
        self, trading_client: HyperscaledClient
    ) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = {"assetPositions": []}
        mock_response.raise_for_status = MagicMock()

        async def mock_post(url: str, json: dict) -> MagicMock:
            return mock_response

        trading_client.trade._client.http.post = mock_post  # type: ignore[assignment]

        with pytest.raises(HyperscaledError, match="No open position"):
            await trading_client.trade.set_tp_sl_async(
                pair="BTC-USDC", stop_loss=Decimal("60000"),
            )

    async def test_set_tp_sl_requires_at_least_one_param(
        self, trading_client: HyperscaledClient
    ) -> None:
        with pytest.raises(ValueError, match="At least one of"):
            await trading_client.trade.set_tp_sl_async(pair="BTC-USDC")

    async def test_set_tp_sl_cancels_only_targeted_oids(
        self, trading_client: HyperscaledClient
    ) -> None:
        mock_exchange = MagicMock()
        mock_exchange.bulk_cancel.return_value = _hl_cancel_response("success", "success")
        mock_exchange.order.return_value = _hl_trigger_resting_response(oid=77777)
        trading_client.trade._exchange = mock_exchange

        mock_info = MagicMock()
        existing = _frontend_open_orders_tp_sl(
            tp_oid=111, sl_oid=222, sz="0.01",
        )
        mock_info.frontend_open_orders.return_value = existing
        trading_client.trade._info = mock_info

        mock_response = MagicMock()
        mock_response.json.return_value = _clearinghouse_with_position()
        mock_response.raise_for_status = MagicMock()

        async def mock_post(url: str, json: dict) -> MagicMock:
            if json.get("type") == "allMids":
                mid_resp = MagicMock()
                mid_resp.json.return_value = {"BTC": "67946.0"}
                mid_resp.raise_for_status = MagicMock()
                return mid_resp
            return mock_response

        trading_client.trade._client.http.post = mock_post  # type: ignore[assignment]

        await trading_client.trade.set_tp_sl_async(
            pair="BTC-USDC", stop_loss=Decimal("60000"),
        )

        # Should cancel only the two existing TP/SL trigger orders
        cancel_args = mock_exchange.bulk_cancel.call_args[0][0]
        cancelled_oids = {req["oid"] for req in cancel_args}
        assert 111 in cancelled_oids
        assert 222 in cancelled_oids

    async def test_set_tp_sl_aborts_on_partial_cancel_failure(
        self, trading_client: HyperscaledClient
    ) -> None:
        """If one cancel succeeds but another fails, replacement should NOT proceed."""
        mock_exchange = MagicMock()
        mock_exchange.bulk_cancel.return_value = _hl_cancel_response(
            "success", {"error": "Order not found"},
        )
        trading_client.trade._exchange = mock_exchange

        mock_info = MagicMock()
        existing = _frontend_open_orders_tp_sl(tp_oid=111, sl_oid=222, sz="0.01")
        mock_info.frontend_open_orders.return_value = existing
        trading_client.trade._info = mock_info

        mock_response = MagicMock()
        mock_response.json.return_value = _clearinghouse_with_position()
        mock_response.raise_for_status = MagicMock()

        async def mock_post(url: str, json: dict) -> MagicMock:
            if json.get("type") == "allMids":
                mid_resp = MagicMock()
                mid_resp.json.return_value = {"BTC": "67946.0"}
                mid_resp.raise_for_status = MagicMock()
                return mid_resp
            return mock_response

        trading_client.trade._client.http.post = mock_post  # type: ignore[assignment]

        with pytest.raises(HyperscaledError, match="Partial cancel failure"):
            await trading_client.trade.set_tp_sl_async(
                pair="BTC-USDC",
                take_profit=Decimal("80000"),
                stop_loss=Decimal("50000"),
            )

        # bulk_orders (placement) should NOT have been called since cancel failed
        mock_exchange.bulk_orders.assert_not_called()
        mock_exchange.order.assert_not_called()

    async def test_set_tp_sl_registers_trailing_state(
        self, trading_client: HyperscaledClient
    ) -> None:
        mock_exchange = MagicMock()
        mock_exchange.bulk_cancel.return_value = _hl_cancel_response("success")
        mock_exchange.order.return_value = _hl_trigger_resting_response(oid=88888)
        trading_client.trade._exchange = mock_exchange

        mock_info = MagicMock()
        mock_info.frontend_open_orders.return_value = []
        trading_client.trade._info = mock_info

        mock_response = MagicMock()
        mock_response.json.return_value = _clearinghouse_with_position()
        mock_response.raise_for_status = MagicMock()

        async def mock_post(url: str, json: dict) -> MagicMock:
            if json.get("type") == "allMids":
                mid_resp = MagicMock()
                mid_resp.json.return_value = {"BTC": "67946.0"}
                mid_resp.raise_for_status = MagicMock()
                return mid_resp
            return mock_response

        trading_client.trade._client.http.post = mock_post  # type: ignore[assignment]

        await trading_client.trade.set_tp_sl_async(
            pair="BTC-USDC",
            trailing_stop={"trailing_percent": 0.03},
        )

        assert "BTC" in trading_client.trade._trailing_state
        state = trading_client.trade._trailing_state["BTC"]
        assert state["side"] == "long"
        assert state["trailing_stop"] == {"trailing_percent": 0.03}
        assert state["current_sl_oid"] == "88888"


# ── update_trailing_stops ─────────────────────────────────────


class TestUpdateTrailingStops:
    async def test_update_trailing_stops_ratchets(
        self, trading_client: HyperscaledClient
    ) -> None:
        mock_exchange = MagicMock()
        mock_exchange.order.return_value = _hl_trigger_resting_response(oid=99999)
        mock_exchange.cancel.return_value = _hl_cancel_response("success")
        trading_client.trade._exchange = mock_exchange

        trading_client.trade._trailing_state["BTC"] = {
            "side": "long",
            "best_price": Decimal("100000"),
            "trailing_stop": {"trailing_percent": 0.02},
            "fixed_sl": None,
            "current_sl_oid": "88888",
            "position_sz": 0.01,
            "degraded": False,
            "last_error": None,
        }

        # Mock mid price higher than best_price
        async def mock_mid(hl_name: str) -> Decimal:
            return Decimal("105000")

        trading_client.trade._fetch_mid_price = mock_mid  # type: ignore[assignment]

        updates = await trading_client.trade.update_trailing_stops_async()

        assert len(updates) == 1
        assert updates[0]["status"] == "updated"
        assert trading_client.trade._trailing_state["BTC"]["current_sl_oid"] == "99999"
        assert trading_client.trade._trailing_state["BTC"]["best_price"] == Decimal("105000")

    async def test_update_trailing_stops_no_change(
        self, trading_client: HyperscaledClient
    ) -> None:
        trading_client.trade._trailing_state["BTC"] = {
            "side": "long",
            "best_price": Decimal("100000"),
            "trailing_stop": {"trailing_percent": 0.02},
            "fixed_sl": None,
            "current_sl_oid": "88888",
            "position_sz": 0.01,
            "degraded": False,
            "last_error": None,
        }

        # Price moved down → no update for LONG
        async def mock_mid(hl_name: str) -> Decimal:
            return Decimal("95000")

        trading_client.trade._fetch_mid_price = mock_mid  # type: ignore[assignment]

        updates = await trading_client.trade.update_trailing_stops_async()
        assert len(updates) == 0

    async def test_update_trailing_stops_replacement_failure_keeps_old_oid(
        self, trading_client: HyperscaledClient
    ) -> None:
        mock_exchange = MagicMock()
        mock_exchange.order.side_effect = ConnectionError("timeout")
        trading_client.trade._exchange = mock_exchange

        trading_client.trade._trailing_state["BTC"] = {
            "side": "long",
            "best_price": Decimal("100000"),
            "trailing_stop": {"trailing_percent": 0.02},
            "fixed_sl": None,
            "current_sl_oid": "88888",
            "position_sz": 0.01,
            "degraded": False,
            "last_error": None,
        }

        async def mock_mid(hl_name: str) -> Decimal:
            return Decimal("105000")

        trading_client.trade._fetch_mid_price = mock_mid  # type: ignore[assignment]

        updates = await trading_client.trade.update_trailing_stops_async()

        assert len(updates) == 1
        assert updates[0]["status"] == "failed"
        assert trading_client.trade._trailing_state["BTC"]["current_sl_oid"] == "88888"
        assert trading_client.trade._trailing_state["BTC"]["degraded"] is True
        # best_price must NOT advance on failure — otherwise the ratchet
        # would be permanently stuck at this level on the next poll.
        assert trading_client.trade._trailing_state["BTC"]["best_price"] == Decimal("100000")

    async def test_update_trailing_stops_cancel_failure_marks_degraded(
        self, trading_client: HyperscaledClient
    ) -> None:
        mock_exchange = MagicMock()
        mock_exchange.order.return_value = _hl_trigger_resting_response(oid=99999)
        mock_exchange.cancel.side_effect = ConnectionError("cancel timeout")
        trading_client.trade._exchange = mock_exchange

        trading_client.trade._trailing_state["BTC"] = {
            "side": "long",
            "best_price": Decimal("100000"),
            "trailing_stop": {"trailing_percent": 0.02},
            "fixed_sl": None,
            "current_sl_oid": "88888",
            "position_sz": 0.01,
            "degraded": False,
            "last_error": None,
        }

        async def mock_mid(hl_name: str) -> Decimal:
            return Decimal("105000")

        trading_client.trade._fetch_mid_price = mock_mid  # type: ignore[assignment]

        updates = await trading_client.trade.update_trailing_stops_async()

        assert len(updates) == 1
        assert updates[0]["status"] == "partial_failure"
        assert trading_client.trade._trailing_state["BTC"]["degraded"] is True
        # New OID should be tracked despite cancel failure
        assert trading_client.trade._trailing_state["BTC"]["current_sl_oid"] == "99999"

    async def test_update_trailing_stops_empty_state(
        self, trading_client: HyperscaledClient
    ) -> None:
        updates = await trading_client.trade.update_trailing_stops_async()
        assert updates == []


# ── Open orders trigger mapping ───────────────────────────────


class TestOpenOrdersTriggerMapping:
    async def test_open_orders_maps_trigger_order(
        self, trading_client: HyperscaledClient
    ) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = _frontend_open_orders_tp_sl()
        mock_response.raise_for_status = MagicMock()

        async def mock_post(url: str, json: dict) -> MagicMock:
            return mock_response

        trading_client.portfolio._client.http.post = mock_post  # type: ignore[assignment]

        orders = await trading_client.portfolio.open_orders_async()

        assert len(orders) == 2
        tp_orders = [o for o in orders if o.take_profit is not None]
        sl_orders = [o for o in orders if o.stop_loss is not None]
        assert len(tp_orders) == 1
        assert len(sl_orders) == 1
        assert tp_orders[0].order_type == "market"
        assert sl_orders[0].order_type == "market"


# ── Model tests ──────────────────────────────────────────────


class TestOrderModelNewFields:
    def test_order_model_defaults(self) -> None:
        from datetime import datetime, timezone

        order = Order(
            pair="BTC-USDC",
            side="long",
            order_type="market",
            status="filled",
            created_at=datetime.now(timezone.utc),
        )
        assert order.filled_size is None
        assert order.trailing_stop is None
        assert order.tp_order_id is None
        assert order.sl_order_id is None
        assert order.trigger_status == "not_requested"
        assert order.trigger_error is None

    def test_order_model_with_trigger_fields(self) -> None:
        from datetime import datetime, timezone

        order = Order(
            pair="BTC-USDC",
            side="long",
            order_type="market",
            status="filled",
            filled_size=Decimal("0.01"),
            trailing_stop={"trailing_percent": 0.02},
            tp_order_id="111",
            sl_order_id="222",
            trigger_status="placed",
            created_at=datetime.now(timezone.utc),
        )
        assert order.filled_size == Decimal("0.01")
        assert order.trailing_stop == {"trailing_percent": 0.02}
        assert order.tp_order_id == "111"
        assert order.sl_order_id == "222"
        assert order.trigger_status == "placed"

    def test_order_model_serialization(self) -> None:
        from datetime import datetime, timezone

        order = Order(
            pair="BTC-USDC",
            side="long",
            order_type="market",
            status="filled",
            filled_size=Decimal("0.01"),
            trailing_stop={"trailing_percent": 0.02},
            tp_order_id="111",
            sl_order_id="222",
            trigger_status="placed",
            trigger_error=None,
            created_at=datetime.now(timezone.utc),
        )
        data = order.model_dump(mode="json")
        assert data["filled_size"] == "0.01"
        assert data["trailing_stop"] == {"trailing_percent": 0.02}
        assert data["tp_order_id"] == "111"
        assert data["trigger_status"] == "placed"
