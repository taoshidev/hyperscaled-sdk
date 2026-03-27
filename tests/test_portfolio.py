"""Tests for SDK-013 — open positions and orders (portfolio reads)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from hyperscaled.exceptions import HyperscaledError
from hyperscaled.models.trading import ClosedPosition, Order, Position
from hyperscaled.sdk.client import HyperscaledClient

VALID_ADDRESS = "0x" + "a1" * 20

runner = CliRunner()


# ── Fixtures / helpers ────────────────────────────────────────


def _position_entry(
    *,
    trade_pair: str = "BTC/USD",
    position_type: str = "LONG",
    is_closed: bool = False,
    average_entry_price: float = 100000.0,
    net_leverage: float = 0.15,
    current_return: float = 1.05,
    realized_pnl: float = 0.0,
    open_ms: int = 1710000000000,
    close_ms: int = 0,
    return_at_close: float = 1.0,
    position_uuid: str | None = None,
    filled_orders: dict | None = None,
    unfilled_orders: list | None = None,
) -> dict:
    """Build a compact position blob matching the new dashboard format."""
    result: dict = {
        "tp": trade_pair,
        "t": position_type,
        "o": open_ms,
        "r": current_return,
        "ap": average_entry_price,
        "rp": realized_pnl,
    }
    if position_uuid is not None:
        result["_uuid"] = position_uuid
    if net_leverage:
        result["nl"] = net_leverage
    if is_closed:
        result["c"] = close_ms
        result["rc"] = return_at_close
    if filled_orders:
        result["fo"] = filled_orders
    if unfilled_orders:
        result["uo"] = unfilled_orders
    return result


def _order_entry(
    *,
    order_uuid: str = "order-uuid-1",
    trade_pair: list | None = None,
    order_type: str = "LONG",
    execution_type: str = "LIMIT",
    quantity: float | None = 0.01,
    value: float | None = None,
    limit_price: float | None = 95000.0,
    take_profit: float | None = None,
    stop_loss: float | None = None,
    processed_ms: int = 1710000000000,
) -> dict:
    return {
        "trade_pair_id": (trade_pair or ["BTCUSD", "BTC/USD"])[0],
        "trade_pair": trade_pair or ["BTCUSD", "BTC/USD"],
        "order_type": order_type,
        "execution_type": execution_type,
        "quantity": quantity,
        "value": value,
        "leverage": None,
        "price": 0,
        "bid": 0,
        "ask": 0,
        "slippage": 0,
        "quote_usd_rate": 0.0,
        "usd_base_rate": 0.0,
        "processed_ms": processed_ms,
        "order_uuid": order_uuid,
        "limit_price": limit_price,
        "take_profit": take_profit,
        "stop_loss": stop_loss,
        "src": 0,
        "price_sources": [],
        "margin_loan": 0.0,
        "bracket_orders": None,
        "is_hl_taker": None,
    }


def _dashboard_payload(
    *,
    positions: list | None = None,
) -> dict:
    # Convert position list to the new dict-keyed-by-uuid format
    positions_dict: dict = {}
    if positions is not None:
        for i, pos in enumerate(positions):
            uuid = pos.pop("_uuid", f"pos-uuid-{i}")
            positions_dict[uuid] = pos

    return {
        "status": "success",
        "dashboard": {
            "subaccount_info": {
                "synthetic_hotkey": "entity_hotkey_0",
                "subaccount_uuid": "uuid-1",
                "subaccount_id": 0,
                "asset_class": "crypto",
                "account_size": 10000.0,
                "status": "active",
                "created_at_ms": 1700000000000,
                "eliminated_at_ms": None,
                "hl_address": VALID_ADDRESS,
                "payout_address": VALID_ADDRESS,
            },
            "positions": {
                "positions": positions_dict,
                "total_leverage": 0.0,
                "positions_time_ms": 1710000000000,
            },
            "drawdown": {
                "current_equity": 1.0,
                "daily_open_equity": 1.0,
                "eod_hwm": 1.0,
                "last_eod_equity": 1.0,
                "intraday_drawdown_pct": 0,
                "eod_drawdown_pct": 0,
                "intraday_drawdown_threshold": 0.05,
                "eod_drawdown_threshold": 0.05,
            },
            "challenge_period": {
                "bucket": "SUBACCOUNT_FUNDED",
                "start_time_ms": 1700000000000,
            },
        },
        "timestamp": 1710000000000,
    }


def _make_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    handler: httpx.MockTransport,
    *,
    http_handler: httpx.MockTransport | None = None,
) -> HyperscaledClient:
    monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
    client = HyperscaledClient(base_url="https://api.example.com")
    client._http = httpx.AsyncClient(
        transport=http_handler or handler, base_url="https://api.example.com"
    )
    client._validator_http = httpx.AsyncClient(
        transport=handler, base_url="https://validator.example.com"
    )
    client.config.set_value("wallet.hl_address", VALID_ADDRESS)
    return client


def _hyperscaled_cli_mock_init(
    payload: dict, *, http_payload: dict | list | None = None
):
    """Minimal ``HyperscaledClient.__init__`` for Typer CLI tests (portfolio reads).

    ``payload`` is served by the validator HTTP client.
    ``http_payload`` (if given) is served by the main HTTP client (e.g. HL info API).
    When ``http_payload`` is ``None`` the main HTTP client uses ``payload`` too.
    """
    validator_transport = _transport_for(payload)
    http_transport = _transport_for(http_payload) if http_payload is not None else validator_transport

    def mock_init(self, **kwargs):
        cfg_mod = __import__("hyperscaled.sdk.config", fromlist=["Config"])
        self._config = cfg_mod.Config.load()
        self._config.set_value("wallet.hl_address", VALID_ADDRESS)
        self._hl_private_key = None
        self._http = httpx.AsyncClient(
            transport=http_transport, base_url="https://api.example.com"
        )
        self._owns_http = True
        self._validator_http = httpx.AsyncClient(
            transport=validator_transport, base_url="https://validator.example.com"
        )
        self._owns_validator_http = True

    return mock_init


def _transport_for(payload: dict | list, status_code: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=payload)

    return httpx.MockTransport(handler)


def _hl_clearinghouse_payload(
    positions: list[dict] | None = None,
) -> dict:
    """Build a mock HL clearinghouseState response."""
    return {
        "assetPositions": positions or [],
        "marginSummary": {},
    }


def _hl_asset_position(
    *,
    coin: str = "BTC",
    szi: str = "0.015",
    entry_px: str = "100000.0",
    position_value: str = "1515.0",
    liquidation_px: str = "42000.0",
    unrealized_pnl: str = "15.0",
) -> dict:
    """Build a single HL clearinghouse asset position entry."""
    return {
        "position": {
            "coin": coin,
            "szi": szi,
            "entryPx": entry_px,
            "positionValue": position_value,
            "liquidationPx": liquidation_px,
            "unrealizedPnl": unrealized_pnl,
        },
        "type": "oneWay",
    }


def _transport_404() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "No subaccount found"})

    return httpx.MockTransport(handler)


def _transport_500() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "Internal server error"})

    return httpx.MockTransport(handler)


# ── Open positions tests ──────────────────────────────────────


class TestOpenPositions:
    async def test_open_positions_populated(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = _dashboard_payload(positions=[_position_entry()])
        client = _make_client(tmp_path, monkeypatch, _transport_for(payload))

        positions = await client.portfolio.open_positions_async()

        assert len(positions) == 1
        pos = positions[0]
        assert isinstance(pos, Position)
        assert pos.symbol == "BTC-USDC"
        assert pos.side == "long"
        assert pos.size == Decimal("0.015")
        assert pos.position_value == Decimal("1500.0")
        assert pos.entry_price == Decimal("100000.0")
        assert pos.mark_price is None
        assert pos.liquidation_price is None
        assert pos.unrealized_pnl == Decimal("75.0")

    async def test_open_positions_filters_closed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        entries = [
            _position_entry(is_closed=False),
            _position_entry(is_closed=True),
        ]
        payload = _dashboard_payload(positions=entries)
        client = _make_client(tmp_path, monkeypatch, _transport_for(payload))

        positions = await client.portfolio.open_positions_async()

        assert len(positions) == 1
        assert positions[0].side == "long"

    async def test_open_positions_filters_flat(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        entries = [_position_entry(position_type="FLAT")]
        payload = _dashboard_payload(positions=entries)
        client = _make_client(tmp_path, monkeypatch, _transport_for(payload))

        positions = await client.portfolio.open_positions_async()

        assert len(positions) == 0

    async def test_open_positions_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = _dashboard_payload(positions=[])
        client = _make_client(tmp_path, monkeypatch, _transport_for(payload))

        positions = await client.portfolio.open_positions_async()

        assert positions == []

    async def test_open_positions_extracts_tp_sl(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fo = {"order-1": {"tk": 110000.0, "sl": 95000.0, "t": "LONG", "v": 1500, "e": "MARKET", "p": 1710000000000}}
        entry = _position_entry(filled_orders=fo)
        payload = _dashboard_payload(positions=[entry])
        client = _make_client(tmp_path, monkeypatch, _transport_for(payload))

        positions = await client.portfolio.open_positions_async()

        assert positions[0].take_profit == Decimal("110000.0")
        assert positions[0].stop_loss == Decimal("95000.0")

    async def test_open_positions_short_side(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        entry = _position_entry(position_type="SHORT")
        payload = _dashboard_payload(positions=[entry])
        client = _make_client(tmp_path, monkeypatch, _transport_for(payload))

        positions = await client.portfolio.open_positions_async()

        assert positions[0].side == "short"

    async def test_open_positions_pair_normalization(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        entry = _position_entry(trade_pair="ETH/USD")
        payload = _dashboard_payload(positions=[entry])
        client = _make_client(tmp_path, monkeypatch, _transport_for(payload))

        positions = await client.portfolio.open_positions_async()

        assert positions[0].symbol == "ETH-USDC"

    async def test_open_positions_with_hl_mark_and_liq_prices(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """mark_price and liquidation_price are populated from HL clearinghouse."""
        dashboard = _dashboard_payload(positions=[_position_entry()])
        hl_ch = _hl_clearinghouse_payload(
            positions=[_hl_asset_position(
                coin="BTC",
                szi="0.015",
                position_value="1515.0",
                liquidation_px="42000.0",
            )]
        )
        client = _make_client(
            tmp_path, monkeypatch, _transport_for(dashboard),
            http_handler=_transport_for(hl_ch),
        )

        positions = await client.portfolio.open_positions_async()

        assert len(positions) == 1
        pos = positions[0]
        # mark_price = abs(1515.0 / 0.015) = 101000
        assert pos.mark_price == Decimal("101000")
        assert pos.liquidation_price == Decimal("42000.0")

    async def test_open_positions_hl_fetch_failure_graceful(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If HL clearinghouse fetch fails, positions still work with None prices."""
        dashboard = _dashboard_payload(positions=[_position_entry()])
        client = _make_client(
            tmp_path, monkeypatch, _transport_for(dashboard),
            http_handler=_transport_for({}, status_code=500),
        )

        positions = await client.portfolio.open_positions_async()

        assert len(positions) == 1
        assert positions[0].mark_price is None
        assert positions[0].liquidation_price is None

    async def test_open_positions_hl_multiple_coins(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Each position gets matched to its coin in the HL data."""
        entries = [
            _position_entry(trade_pair="BTC/USD"),
            _position_entry(
                trade_pair="ETH/USD",
                net_leverage=0.3,
                average_entry_price=3000.0,
            ),
        ]
        dashboard = _dashboard_payload(positions=entries)
        hl_ch = _hl_clearinghouse_payload(positions=[
            _hl_asset_position(coin="BTC", szi="0.015", position_value="1515.0", liquidation_px="42000.0"),
            _hl_asset_position(coin="ETH", szi="1.0", position_value="3100.0", liquidation_px="1500.0"),
        ])
        client = _make_client(
            tmp_path, monkeypatch, _transport_for(dashboard),
            http_handler=_transport_for(hl_ch),
        )

        positions = await client.portfolio.open_positions_async()

        assert len(positions) == 2
        btc = next(p for p in positions if p.symbol == "BTC-USDC")
        eth = next(p for p in positions if p.symbol == "ETH-USDC")
        assert btc.mark_price == Decimal("101000")
        assert btc.liquidation_price == Decimal("42000.0")
        assert eth.mark_price == Decimal("3100")
        assert eth.liquidation_price == Decimal("1500.0")

    def test_open_positions_sync(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = _dashboard_payload(positions=[_position_entry()])
        client = _make_client(tmp_path, monkeypatch, _transport_for(payload))

        positions = client.portfolio.open_positions()

        assert len(positions) == 1
        assert isinstance(positions[0], Position)


# ── Open orders tests ─────────────────────────────────────────


def _hl_order_entry(
    *,
    coin: str = "BTC",
    limit_px: str = "95000.0",
    oid: int = 123456,
    side: str = "B",
    sz: str = "0.01",
    timestamp: int = 1710000000000,
) -> dict:
    """Hyperliquid info API open-order response entry."""
    return {
        "coin": coin,
        "limitPx": limit_px,
        "oid": oid,
        "side": side,
        "sz": sz,
        "timestamp": timestamp,
    }


class TestOpenOrders:
    async def test_open_orders_populated(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        hl_orders = [_hl_order_entry()]
        dashboard = _dashboard_payload()
        client = _make_client(
            tmp_path,
            monkeypatch,
            _transport_for(dashboard),
            http_handler=_transport_for(hl_orders),
        )

        orders = await client.portfolio.open_orders_async()

        assert len(orders) == 1
        order = orders[0]
        assert isinstance(order, Order)
        assert order.pair == "BTC-USDC"
        assert order.side == "long"
        assert order.order_type == "limit"
        assert order.status == "open"
        assert order.limit_price == Decimal("95000.0")
        assert order.size == Decimal("0.01")
        assert order.order_id == "123456"
        assert order.hl_order_id == "123456"
        assert order.scaling_ratio is None
        assert order.fill_price is None

    async def test_open_orders_sell_side(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        hl_orders = [_hl_order_entry(side="A")]
        client = _make_client(
            tmp_path, monkeypatch, _transport_for({}),
            http_handler=_transport_for(hl_orders),
        )

        orders = await client.portfolio.open_orders_async()

        assert orders[0].side == "short"

    async def test_open_orders_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_client(
            tmp_path, monkeypatch, _transport_for({}),
            http_handler=_transport_for([]),
        )

        orders = await client.portfolio.open_orders_async()

        assert orders == []

    async def test_open_orders_non_list_response(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_client(
            tmp_path, monkeypatch, _transport_for({}),
            http_handler=_transport_for({}),
        )

        orders = await client.portfolio.open_orders_async()

        assert orders == []

    async def test_open_orders_multiple_coins(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        hl_orders = [
            _hl_order_entry(coin="BTC", oid=1),
            _hl_order_entry(coin="ETH", oid=2, side="A"),
        ]
        client = _make_client(
            tmp_path, monkeypatch, _transport_for({}),
            http_handler=_transport_for(hl_orders),
        )

        orders = await client.portfolio.open_orders_async()

        assert len(orders) == 2
        assert orders[0].pair == "BTC-USDC"
        assert orders[1].pair == "ETH-USDC"
        assert orders[1].side == "short"

    def test_open_orders_sync(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        hl_orders = [_hl_order_entry()]
        client = _make_client(
            tmp_path, monkeypatch, _transport_for({}),
            http_handler=_transport_for(hl_orders),
        )

        orders = client.portfolio.open_orders()

        assert len(orders) == 1
        assert isinstance(orders[0], Order)


# ── Dashboard error handling ──────────────────────────────────


class TestDashboardErrors:
    async def test_fetch_dashboard_404(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_client(tmp_path, monkeypatch, _transport_404())

        with pytest.raises(HyperscaledError, match="No validator dashboard"):
            await client.portfolio.open_positions_async()

    async def test_fetch_dashboard_http_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_client(tmp_path, monkeypatch, _transport_500())

        with pytest.raises(HyperscaledError, match="Failed to fetch"):
            await client.portfolio.open_positions_async()

    async def test_fetch_dashboard_missing_hl_address(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bad_payload = {"status": "success"}
        client = _make_client(tmp_path, monkeypatch, _transport_for(bad_payload))

        with pytest.raises(HyperscaledError, match="unexpected shape"):
            await client.portfolio.open_positions_async()

    async def test_no_wallet_configured(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient(base_url="https://api.example.com")

        with pytest.raises(HyperscaledError, match="No Hyperliquid wallet configured"):
            await client.portfolio.open_positions_async()


# ── CLI tests ─────────────────────────────────────────────────


class TestPositionsCLI:
    def test_positions_open_table(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = _dashboard_payload(positions=[_position_entry()])
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        from hyperscaled.cli.positions import app as positions_app

        monkeypatch.setattr(
            HyperscaledClient, "__init__", _hyperscaled_cli_mock_init(payload)
        )
        result = runner.invoke(positions_app, ["open"])
        assert result.exit_code == 0
        assert "BTC-USDC" in result.output
        assert "long" in result.output

    def test_positions_open_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = _dashboard_payload(positions=[_position_entry()])
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        from hyperscaled.cli.positions import app as positions_app

        monkeypatch.setattr(
            HyperscaledClient, "__init__", _hyperscaled_cli_mock_init(payload)
        )
        result = runner.invoke(positions_app, ["open", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["symbol"] == "BTC-USDC"

    def test_positions_open_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = _dashboard_payload(positions=[])
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        from hyperscaled.cli.positions import app as positions_app

        monkeypatch.setattr(
            HyperscaledClient, "__init__", _hyperscaled_cli_mock_init(payload)
        )
        result = runner.invoke(positions_app, ["open"])
        assert result.exit_code == 0
        assert "No open positions" in result.output


class TestOrdersCLI:
    def test_orders_open_table(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        hl_orders = [_hl_order_entry()]
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        from hyperscaled.cli.orders import app as orders_app

        monkeypatch.setattr(
            HyperscaledClient, "__init__",
            _hyperscaled_cli_mock_init(_dashboard_payload(), http_payload=hl_orders),
        )
        result = runner.invoke(orders_app, ["open"])
        assert result.exit_code == 0
        assert "BTC-USDC" in result.output
        assert "limit" in result.output

    def test_orders_open_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        hl_orders = [_hl_order_entry()]
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        from hyperscaled.cli.orders import app as orders_app

        monkeypatch.setattr(
            HyperscaledClient, "__init__",
            _hyperscaled_cli_mock_init(_dashboard_payload(), http_payload=hl_orders),
        )
        result = runner.invoke(orders_app, ["open", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["pair"] == "BTC-USDC"
        assert data[0]["status"] == "open"

    def test_orders_open_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        from hyperscaled.cli.orders import app as orders_app

        monkeypatch.setattr(
            HyperscaledClient, "__init__",
            _hyperscaled_cli_mock_init(_dashboard_payload(), http_payload=[]),
        )
        result = runner.invoke(orders_app, ["open"])
        assert result.exit_code == 0
        assert "No open orders" in result.output


# ── Position history tests ────────────────────────────────────


def _hl_fill_entry(
    *,
    coin: str = "BTC",
    px: str = "85000.0",
    sz: str = "0.001",
    side: str = "B",
    time: int = 1710000000000,
    oid: int = 999,
) -> dict:
    """Hyperliquid userFills response entry."""
    return {
        "coin": coin,
        "px": px,
        "sz": sz,
        "side": side,
        "time": time,
        "oid": oid,
        "crossed": True,
        "fee": "0.85",
        "hash": "0xabc",
        "tid": 12345,
    }


class TestPositionHistory:
    async def test_position_history_returns_closed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        entries = [
            _position_entry(is_closed=True, close_ms=1710100000000),
            _position_entry(is_closed=False),
        ]
        payload = _dashboard_payload(positions=entries)
        client = _make_client(tmp_path, monkeypatch, _transport_for(payload))

        positions = await client.portfolio.position_history_async()

        assert len(positions) == 1
        pos = positions[0]
        assert isinstance(pos, ClosedPosition)
        assert pos.symbol == "BTC-USDC"
        assert pos.close_time == datetime.fromtimestamp(1710100000000 / 1000, tz=timezone.utc)

    async def test_position_history_date_filter(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Two closed positions at different times
        entries = [
            _position_entry(
                is_closed=True,
                close_ms=1704067200000,  # 2024-01-01 00:00 UTC
            ),
            _position_entry(
                is_closed=True,
                close_ms=1706745600000,  # 2024-02-01 00:00 UTC
            ),
        ]
        payload = _dashboard_payload(positions=entries)
        client = _make_client(tmp_path, monkeypatch, _transport_for(payload))

        from_dt = datetime(2024, 1, 15, tzinfo=timezone.utc)
        to_dt = datetime(2024, 2, 15, tzinfo=timezone.utc)
        positions = await client.portfolio.position_history_async(
            from_date=from_dt, to_date=to_dt,
        )

        assert len(positions) == 1
        assert positions[0].close_time == datetime.fromtimestamp(
            1706745600000 / 1000, tz=timezone.utc,
        )

    async def test_position_history_pair_filter(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        entries = [
            _position_entry(
                is_closed=True,
                close_ms=1710100000000,
                trade_pair="BTC/USD",
            ),
            _position_entry(
                is_closed=True,
                close_ms=1710100000000,
                trade_pair="ETH/USD",
            ),
        ]
        payload = _dashboard_payload(positions=entries)
        client = _make_client(tmp_path, monkeypatch, _transport_for(payload))

        positions = await client.portfolio.position_history_async(pair="ETH-USDC")

        assert len(positions) == 1
        assert positions[0].symbol == "ETH-USDC"

    async def test_position_history_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = _dashboard_payload(positions=[])
        client = _make_client(tmp_path, monkeypatch, _transport_for(payload))

        positions = await client.portfolio.position_history_async()

        assert positions == []

    async def test_position_history_empty_date_range(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Empty date range returns empty list, not error."""
        entries = [
            _position_entry(
                is_closed=True,
                close_ms=1710100000000,
            ),
        ]
        payload = _dashboard_payload(positions=entries)
        client = _make_client(tmp_path, monkeypatch, _transport_for(payload))

        # Date range that excludes everything
        from_dt = datetime(2020, 1, 1, tzinfo=timezone.utc)
        to_dt = datetime(2020, 1, 2, tzinfo=timezone.utc)
        positions = await client.portfolio.position_history_async(
            from_date=from_dt, to_date=to_dt,
        )

        assert positions == []

    async def test_position_history_realized_pnl(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        entry = _position_entry(
            is_closed=True,
            close_ms=1710100000000,
            realized_pnl=250.0,
        )
        payload = _dashboard_payload(positions=[entry])
        client = _make_client(tmp_path, monkeypatch, _transport_for(payload))

        positions = await client.portfolio.position_history_async()

        assert len(positions) == 1
        assert positions[0].realized_pnl == Decimal("250.0")

    def test_position_history_sync(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        entries = [_position_entry(is_closed=True, close_ms=1710100000000)]
        payload = _dashboard_payload(positions=entries)
        client = _make_client(tmp_path, monkeypatch, _transport_for(payload))

        positions = client.portfolio.position_history()

        assert len(positions) == 1
        assert isinstance(positions[0], ClosedPosition)


# ── Order history tests ───────────────────────────────────────


class TestOrderHistory:
    async def test_order_history_returns_fills(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fills = [_hl_fill_entry()]
        dashboard = _dashboard_payload()
        client = _make_client(
            tmp_path, monkeypatch, _transport_for(dashboard),
            http_handler=_transport_for(fills),
        )

        orders = await client.portfolio.order_history_async()

        assert len(orders) == 1
        order = orders[0]
        assert isinstance(order, Order)
        assert order.pair == "BTC-USDC"
        assert order.side == "long"
        assert order.status == "filled"
        assert order.fill_price == Decimal("85000.0")
        assert order.size == Decimal("0.001")

    async def test_order_history_pair_filter(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fills = [
            _hl_fill_entry(coin="BTC", oid=1),
            _hl_fill_entry(coin="ETH", oid=2),
        ]
        client = _make_client(
            tmp_path, monkeypatch, _transport_for({}),
            http_handler=_transport_for(fills),
        )

        orders = await client.portfolio.order_history_async(pair="ETH-USDC")

        assert len(orders) == 1
        assert orders[0].pair == "ETH-USDC"

    async def test_order_history_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_client(
            tmp_path, monkeypatch, _transport_for({}),
            http_handler=_transport_for([]),
        )

        orders = await client.portfolio.order_history_async()

        assert orders == []

    async def test_order_history_sell_side(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fills = [_hl_fill_entry(side="A")]
        client = _make_client(
            tmp_path, monkeypatch, _transport_for({}),
            http_handler=_transport_for(fills),
        )

        orders = await client.portfolio.order_history_async()

        assert orders[0].side == "short"

    async def test_order_history_with_dates_uses_fills_by_time(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When dates are provided, should still return results (uses userFillsByTime)."""
        fills = [_hl_fill_entry()]
        client = _make_client(
            tmp_path, monkeypatch, _transport_for({}),
            http_handler=_transport_for(fills),
        )

        from_dt = datetime(2024, 1, 1, tzinfo=timezone.utc)
        to_dt = datetime(2024, 12, 31, tzinfo=timezone.utc)
        orders = await client.portfolio.order_history_async(
            from_date=from_dt, to_date=to_dt,
        )

        assert len(orders) == 1

    def test_order_history_sync(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fills = [_hl_fill_entry()]
        client = _make_client(
            tmp_path, monkeypatch, _transport_for({}),
            http_handler=_transport_for(fills),
        )

        orders = client.portfolio.order_history()

        assert len(orders) == 1
        assert isinstance(orders[0], Order)


# ── Position history CLI tests ────────────────────────────────


class TestPositionHistoryCLI:
    def test_positions_history_table(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        entry = _position_entry(is_closed=True, close_ms=1710100000000, realized_pnl=150.0)
        payload = _dashboard_payload(positions=[entry])
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        from hyperscaled.cli.positions import app as positions_app

        monkeypatch.setattr(
            HyperscaledClient, "__init__", _hyperscaled_cli_mock_init(payload),
        )
        result = runner.invoke(positions_app, ["history"])
        assert result.exit_code == 0
        assert "BTC-USDC" in result.output

    def test_positions_history_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        entry = _position_entry(is_closed=True, close_ms=1710100000000, realized_pnl=150.0)
        payload = _dashboard_payload(positions=[entry])
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        from hyperscaled.cli.positions import app as positions_app

        monkeypatch.setattr(
            HyperscaledClient, "__init__", _hyperscaled_cli_mock_init(payload),
        )
        result = runner.invoke(positions_app, ["history", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["symbol"] == "BTC-USDC"
        assert "realized_pnl" in data[0]
        assert "close_time" in data[0]

    def test_positions_history_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = _dashboard_payload(positions=[])
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        from hyperscaled.cli.positions import app as positions_app

        monkeypatch.setattr(
            HyperscaledClient, "__init__", _hyperscaled_cli_mock_init(payload),
        )
        result = runner.invoke(positions_app, ["history"])
        assert result.exit_code == 0
        assert "No closed positions found" in result.output

    def test_positions_history_with_pair_filter(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        entries = [
            _position_entry(
                is_closed=True, close_ms=1710100000000,
                trade_pair="BTC/USD",
            ),
            _position_entry(
                is_closed=True, close_ms=1710100000000,
                trade_pair="ETH/USD",
            ),
        ]
        payload = _dashboard_payload(positions=entries)
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        from hyperscaled.cli.positions import app as positions_app

        monkeypatch.setattr(
            HyperscaledClient, "__init__", _hyperscaled_cli_mock_init(payload),
        )
        result = runner.invoke(positions_app, ["history", "--pair", "ETH-USDC"])
        assert result.exit_code == 0
        assert "ETH-USDC" in result.output
        assert "BTC-USDC" not in result.output


# ── Order history CLI tests ───────────────────────────────────


class TestOrderHistoryCLI:
    def test_orders_history_table(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fills = [_hl_fill_entry()]
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        from hyperscaled.cli.orders import app as orders_app

        monkeypatch.setattr(
            HyperscaledClient, "__init__",
            _hyperscaled_cli_mock_init(_dashboard_payload(), http_payload=fills),
        )
        result = runner.invoke(orders_app, ["history"])
        assert result.exit_code == 0
        assert "BTC-USDC" in result.output

    def test_orders_history_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fills = [_hl_fill_entry()]
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        from hyperscaled.cli.orders import app as orders_app

        monkeypatch.setattr(
            HyperscaledClient, "__init__",
            _hyperscaled_cli_mock_init(_dashboard_payload(), http_payload=fills),
        )
        result = runner.invoke(orders_app, ["history", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["pair"] == "BTC-USDC"
        assert data[0]["status"] == "filled"
        assert data[0]["fill_price"] is not None

    def test_orders_history_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        from hyperscaled.cli.orders import app as orders_app

        monkeypatch.setattr(
            HyperscaledClient, "__init__",
            _hyperscaled_cli_mock_init(_dashboard_payload(), http_payload=[]),
        )
        result = runner.invoke(orders_app, ["history"])
        assert result.exit_code == 0
        assert "No filled orders found" in result.output

    def test_orders_history_with_pair_filter(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fills = [
            _hl_fill_entry(coin="BTC", oid=1),
            _hl_fill_entry(coin="ETH", oid=2),
        ]
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        from hyperscaled.cli.orders import app as orders_app

        monkeypatch.setattr(
            HyperscaledClient, "__init__",
            _hyperscaled_cli_mock_init(_dashboard_payload(), http_payload=fills),
        )
        result = runner.invoke(orders_app, ["history", "--pair", "ETH-USDC"])
        assert result.exit_code == 0
        assert "ETH-USDC" in result.output
        assert "BTC-USDC" not in result.output
