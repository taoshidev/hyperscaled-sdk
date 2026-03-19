"""Tests for SDK-013 — open positions and orders (portfolio reads)."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from hyperscaled.exceptions import HyperscaledError
from hyperscaled.models.trading import Order, Position
from hyperscaled.sdk.client import HyperscaledClient

VALID_ADDRESS = "0x" + "a1" * 20

runner = CliRunner()


# ── Fixtures / helpers ────────────────────────────────────────


def _position_entry(
    *,
    trade_pair: list | None = None,
    position_type: str = "LONG",
    is_closed_position: bool = False,
    net_quantity: float = 0.015,
    net_value: float = 1500.0,
    average_entry_price: float = 100000.0,
    unrealized_pnl: float = 75.0,
    open_ms: int = 1710000000000,
    close_ms: int = 0,
    orders: list | None = None,
    unfilled_orders: list | None = None,
) -> dict:
    return {
        "miner_hotkey": "entity_hotkey_0",
        "position_uuid": "pos-uuid-1",
        "trade_pair": trade_pair or ["BTCUSD", "BTC/USD", 0.003, 0.001, 0.5],
        "position_type": position_type,
        "is_closed_position": is_closed_position,
        "net_quantity": net_quantity,
        "net_value": net_value,
        "average_entry_price": average_entry_price,
        "unrealized_pnl": unrealized_pnl,
        "open_ms": open_ms,
        "close_ms": close_ms,
        "current_return": 1.05,
        "net_leverage": 0.15,
        "return_at_close": 1.0,
        "cumulative_entry_value": 1500.0,
        "account_size": 10000.0,
        "realized_pnl": 0.0,
        "is_hl": True,
        "orders": orders or [],
        "unfilled_orders": unfilled_orders or [],
    }


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
    limit_orders: list | None = None,
) -> dict:
    return {
        "status": "success",
        "hl_address": VALID_ADDRESS,
        "dashboard": {
            "subaccount_info": {
                "synthetic_hotkey": "entity_hotkey_0",
                "entity_hotkey": "5GhDr",
                "subaccount_id": 0,
                "subaccount_uuid": "uuid",
                "asset_class": "crypto",
                "account_size": 10000.0,
                "status": "active",
                "created_at_ms": 1700000000000,
                "eliminated_at_ms": None,
                "hl_address": VALID_ADDRESS,
            },
            "challenge_period": {"bucket": "SUBACCOUNT_FUNDED", "start_time_ms": 1700000000000},
            "ledger": None,
            "positions": {
                "positions": positions if positions is not None else [],
                "thirty_day_returns": 1.0,
                "all_time_returns": 1.0,
                "n_positions": 0,
                "percentage_profitable": 0.0,
                "total_leverage": 0.0,
            },
            "limit_orders": limit_orders if limit_orders is not None else [],
            "account_size_data": {
                "account_size": 10000.0,
                "balance": 10000.0,
                "capital_used": 0.0,
            },
            "statistics": None,
            "elimination": None,
        },
        "timestamp": 1710000000000,
    }


def _make_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    handler: httpx.MockTransport,
) -> HyperscaledClient:
    monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
    client = HyperscaledClient(base_url="https://api.example.com")
    client._http = httpx.AsyncClient(transport=handler, base_url="https://api.example.com")
    client.config.set_value("wallet.hl_address", VALID_ADDRESS)
    return client


def _transport_for(payload: dict, status_code: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=payload)

    return httpx.MockTransport(handler)


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
            _position_entry(is_closed_position=False),
            _position_entry(is_closed_position=True),
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
        orders = [{"take_profit": 110000.0, "stop_loss": 95000.0}]
        entry = _position_entry(orders=orders)
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
        entry = _position_entry(trade_pair=["ETHUSD", "ETH/USD", 0.003, 0.001, 0.5])
        payload = _dashboard_payload(positions=[entry])
        client = _make_client(tmp_path, monkeypatch, _transport_for(payload))

        positions = await client.portfolio.open_positions_async()

        assert positions[0].symbol == "ETH-USDC"

    def test_open_positions_sync(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = _dashboard_payload(positions=[_position_entry()])
        client = _make_client(tmp_path, monkeypatch, _transport_for(payload))

        positions = client.portfolio.open_positions()

        assert len(positions) == 1
        assert isinstance(positions[0], Position)


# ── Open orders tests ─────────────────────────────────────────


class TestOpenOrders:
    async def test_open_orders_populated(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = _dashboard_payload(limit_orders=[_order_entry()])
        client = _make_client(tmp_path, monkeypatch, _transport_for(payload))

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
        assert order.order_id == "order-uuid-1"
        assert order.hl_order_id is None
        assert order.scaling_ratio is None
        assert order.fill_price is None

    async def test_open_orders_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = _dashboard_payload(limit_orders=[])
        client = _make_client(tmp_path, monkeypatch, _transport_for(payload))

        orders = await client.portfolio.open_orders_async()

        assert orders == []

    async def test_open_orders_none_limit_orders(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = _dashboard_payload(limit_orders=None)
        client = _make_client(tmp_path, monkeypatch, _transport_for(payload))

        orders = await client.portfolio.open_orders_async()

        assert orders == []

    async def test_open_orders_with_tp_sl(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        entry = _order_entry(take_profit=110000.0, stop_loss=90000.0)
        payload = _dashboard_payload(limit_orders=[entry])
        client = _make_client(tmp_path, monkeypatch, _transport_for(payload))

        orders = await client.portfolio.open_orders_async()

        assert orders[0].take_profit == Decimal("110000.0")
        assert orders[0].stop_loss == Decimal("90000.0")

    async def test_open_orders_optional_size_fields(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        entry = _order_entry(quantity=None, value=None)
        payload = _dashboard_payload(limit_orders=[entry])
        client = _make_client(tmp_path, monkeypatch, _transport_for(payload))

        orders = await client.portfolio.open_orders_async()

        assert orders[0].size is None
        assert orders[0].funded_equivalent_size is None

    async def test_open_orders_value_as_funded_size(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        entry = _order_entry(quantity=None, value=5000.0)
        payload = _dashboard_payload(limit_orders=[entry])
        client = _make_client(tmp_path, monkeypatch, _transport_for(payload))

        orders = await client.portfolio.open_orders_async()

        assert orders[0].size is None
        assert orders[0].funded_equivalent_size == Decimal("5000.0")

    def test_open_orders_sync(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = _dashboard_payload(limit_orders=[_order_entry()])
        client = _make_client(tmp_path, monkeypatch, _transport_for(payload))

        orders = client.portfolio.open_orders()

        assert len(orders) == 1
        assert isinstance(orders[0], Order)


# ── Dashboard error handling ──────────────────────────────────


class TestDashboardErrors:
    async def test_fetch_dashboard_404(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_client(tmp_path, monkeypatch, _transport_404())

        with pytest.raises(HyperscaledError, match="not found"):
            await client.portfolio.open_positions_async()

    async def test_fetch_dashboard_http_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_client(tmp_path, monkeypatch, _transport_500())

        with pytest.raises(HyperscaledError, match="Failed to fetch"):
            await client.portfolio.open_positions_async()

    async def test_fetch_dashboard_missing_dashboard_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bad_payload = {"status": "success", "hl_address": VALID_ADDRESS}
        client = _make_client(tmp_path, monkeypatch, _transport_for(bad_payload))

        with pytest.raises(HyperscaledError, match="missing dashboard payload"):
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

        def mock_init(self, **kwargs):
            self._config = __import__("hyperscaled.sdk.config", fromlist=["Config"]).Config.load()
            self._config.set_value("wallet.hl_address", VALID_ADDRESS)
            self._hl_private_key = None
            self._http = httpx.AsyncClient(
                transport=_transport_for(payload), base_url="https://api.example.com"
            )
            self._owns_http = True

        monkeypatch.setattr(HyperscaledClient, "__init__", mock_init)
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

        def mock_init(self, **kwargs):
            self._config = __import__("hyperscaled.sdk.config", fromlist=["Config"]).Config.load()
            self._config.set_value("wallet.hl_address", VALID_ADDRESS)
            self._hl_private_key = None
            self._http = httpx.AsyncClient(
                transport=_transport_for(payload), base_url="https://api.example.com"
            )
            self._owns_http = True

        monkeypatch.setattr(HyperscaledClient, "__init__", mock_init)
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

        def mock_init(self, **kwargs):
            self._config = __import__("hyperscaled.sdk.config", fromlist=["Config"]).Config.load()
            self._config.set_value("wallet.hl_address", VALID_ADDRESS)
            self._hl_private_key = None
            self._http = httpx.AsyncClient(
                transport=_transport_for(payload), base_url="https://api.example.com"
            )
            self._owns_http = True

        monkeypatch.setattr(HyperscaledClient, "__init__", mock_init)
        result = runner.invoke(positions_app, ["open"])
        assert result.exit_code == 0
        assert "No open positions" in result.output


class TestOrdersCLI:
    def test_orders_open_table(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = _dashboard_payload(limit_orders=[_order_entry()])
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        from hyperscaled.cli.orders import app as orders_app

        def mock_init(self, **kwargs):
            self._config = __import__("hyperscaled.sdk.config", fromlist=["Config"]).Config.load()
            self._config.set_value("wallet.hl_address", VALID_ADDRESS)
            self._hl_private_key = None
            self._http = httpx.AsyncClient(
                transport=_transport_for(payload), base_url="https://api.example.com"
            )
            self._owns_http = True

        monkeypatch.setattr(HyperscaledClient, "__init__", mock_init)
        result = runner.invoke(orders_app, ["open"])
        assert result.exit_code == 0
        assert "BTC-USDC" in result.output
        assert "limit" in result.output

    def test_orders_open_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = _dashboard_payload(limit_orders=[_order_entry()])
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        from hyperscaled.cli.orders import app as orders_app

        def mock_init(self, **kwargs):
            self._config = __import__("hyperscaled.sdk.config", fromlist=["Config"]).Config.load()
            self._config.set_value("wallet.hl_address", VALID_ADDRESS)
            self._hl_private_key = None
            self._http = httpx.AsyncClient(
                transport=_transport_for(payload), base_url="https://api.example.com"
            )
            self._owns_http = True

        monkeypatch.setattr(HyperscaledClient, "__init__", mock_init)
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
        payload = _dashboard_payload(limit_orders=[])
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        from hyperscaled.cli.orders import app as orders_app

        def mock_init(self, **kwargs):
            self._config = __import__("hyperscaled.sdk.config", fromlist=["Config"]).Config.load()
            self._config.set_value("wallet.hl_address", VALID_ADDRESS)
            self._hl_private_key = None
            self._http = httpx.AsyncClient(
                transport=_transport_for(payload), base_url="https://api.example.com"
            )
            self._owns_http = True

        monkeypatch.setattr(HyperscaledClient, "__init__", mock_init)
        result = runner.invoke(orders_app, ["open"])
        assert result.exit_code == 0
        assert "No open orders" in result.output

    def test_orders_open_none_size_renders_dashes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        entry = _order_entry(quantity=None, value=None)
        payload = _dashboard_payload(limit_orders=[entry])
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        from hyperscaled.cli.orders import app as orders_app

        def mock_init(self, **kwargs):
            self._config = __import__("hyperscaled.sdk.config", fromlist=["Config"]).Config.load()
            self._config.set_value("wallet.hl_address", VALID_ADDRESS)
            self._hl_private_key = None
            self._http = httpx.AsyncClient(
                transport=_transport_for(payload), base_url="https://api.example.com"
            )
            self._owns_http = True

        monkeypatch.setattr(HyperscaledClient, "__init__", mock_init)
        result = runner.invoke(orders_app, ["open"])
        assert result.exit_code == 0
        assert "--" in result.output
