"""Positions, orders, and account info SDK interface."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any, TypeVar

import httpx

from hyperscaled.exceptions import HyperscaledError
from hyperscaled.models.trading import Order, Position
from hyperscaled.sdk.client import _run_sync

if TYPE_CHECKING:
    from hyperscaled.sdk.client import HyperscaledClient

T = TypeVar("T")

_HL_DASHBOARD_PATH = "/hl/{hl_address}/dashboard"


def _sync_or_async(coro: Coroutine[Any, Any, T]) -> T | Coroutine[Any, Any, T]:
    """Run sync when possible, otherwise return the coroutine for awaiting."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        return coro

    result: T = _run_sync(coro)
    return result


def _decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    if value is None:
        return default
    try:
        return Decimal(str(value))
    except Exception:
        return default


def _dt_from_ms(ms: Any) -> datetime:
    """Convert epoch milliseconds to a timezone-aware UTC datetime."""
    return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc)


def _normalize_trade_pair(raw: Any) -> str:
    """Convert a validator trade_pair tuple into the SDK display format.

    Input is typically ``["BTCUSD", "BTC/USD", fee, min_lev, max_lev]``.
    Output is the SDK-facing format, e.g. ``"BTC-USDC"`` for crypto pairs.
    """
    if isinstance(raw, list) and len(raw) >= 2:
        display = str(raw[1]).upper()
    elif isinstance(raw, str):
        display = raw.upper()
    else:
        return str(raw)

    if "/" in display:
        base, quote = display.split("/", 1)
        if quote == "USD":
            return f"{base}-USDC"
        return f"{base}-{quote}"

    if display.endswith("USD"):
        return f"{display[:-3]}-USDC"
    return display


def _extract_tp_sl(raw_position: dict[str, Any]) -> tuple[Decimal | None, Decimal | None]:
    """Best-effort extraction of TP/SL from embedded orders or unfilled orders."""
    take_profit: Decimal | None = None
    stop_loss: Decimal | None = None

    for order in raw_position.get("orders", []):
        if isinstance(order, dict):
            if order.get("take_profit") is not None and take_profit is None:
                take_profit = _decimal(order["take_profit"])
            if order.get("stop_loss") is not None and stop_loss is None:
                stop_loss = _decimal(order["stop_loss"])

    for uf in raw_position.get("unfilled_orders", []):
        if isinstance(uf, dict):
            if uf.get("take_profit") is not None and take_profit is None:
                take_profit = _decimal(uf["take_profit"])
            if uf.get("stop_loss") is not None and stop_loss is None:
                stop_loss = _decimal(uf["stop_loss"])

    return take_profit, stop_loss


class PortfolioClient:
    """Read-only portfolio visibility for open positions and open orders."""

    def __init__(self, client: HyperscaledClient) -> None:
        self._client = client

    def _resolve_wallet(self) -> str:
        hl_address = self._client.config.wallet.hl_address
        if not hl_address:
            raise HyperscaledError(
                "No Hyperliquid wallet configured. "
                "Run `client.account.setup(wallet)` or `hyperscaled account setup <wallet>` first."
            )
        return hl_address

    async def _fetch_dashboard(self) -> dict[str, Any]:
        hl_address = self._resolve_wallet()
        path = _HL_DASHBOARD_PATH.format(hl_address=hl_address)

        try:
            response = await self._client.http.get(path)
        except httpx.HTTPError as exc:
            raise HyperscaledError(f"Failed to fetch validator dashboard: {exc}") from exc

        if response.status_code == 404:
            raise HyperscaledError(
                "Validator dashboard not found for the configured Hyperliquid wallet."
            )

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HyperscaledError(
                "Failed to fetch validator dashboard: "
                f"{exc.response.status_code} {exc.response.reason_phrase}"
            ) from exc

        payload = response.json()
        dashboard = payload.get("dashboard")
        if not isinstance(dashboard, dict):
            raise HyperscaledError("Validator dashboard response missing dashboard payload")
        return dashboard

    def _map_position(self, raw: dict[str, Any]) -> Position | None:
        """Map a validator position dict to an SDK Position, or None to skip."""
        if raw.get("is_closed_position"):
            return None

        position_type = str(raw.get("position_type", "")).upper()
        if position_type == "FLAT":
            return None

        side = "long" if position_type == "LONG" else "short"
        take_profit, stop_loss = _extract_tp_sl(raw)

        return Position(
            symbol=_normalize_trade_pair(raw.get("trade_pair")),
            side=side,
            size=_decimal(raw.get("net_quantity")),
            position_value=_decimal(raw.get("net_value")),
            entry_price=_decimal(raw.get("average_entry_price")),
            mark_price=None,
            liquidation_price=None,
            unrealized_pnl=_decimal(raw.get("unrealized_pnl")),
            take_profit=take_profit,
            stop_loss=stop_loss,
            open_time=_dt_from_ms(raw.get("open_ms", 0)),
        )

    def _map_order(self, raw: dict[str, Any]) -> Order:
        """Map a validator limit order dict to an SDK Order."""
        order_type_raw = str(raw.get("order_type", "")).upper()
        side = "long" if order_type_raw == "LONG" else "short"

        execution = str(raw.get("execution_type", "market")).lower()
        if execution not in {"market", "limit"}:
            execution = "limit"

        quantity = raw.get("quantity")
        value = raw.get("value")

        return Order(
            order_id=raw.get("order_uuid"),
            hl_order_id=None,
            pair=_normalize_trade_pair(raw.get("trade_pair")),
            side=side,
            size=_decimal(quantity) if quantity is not None else None,
            funded_equivalent_size=_decimal(value) if value is not None else None,
            order_type=execution,
            status="open",
            limit_price=_decimal(raw["limit_price"]) if raw.get("limit_price") is not None else None,
            fill_price=None,
            scaling_ratio=None,
            take_profit=_decimal(raw["take_profit"]) if raw.get("take_profit") is not None else None,
            stop_loss=_decimal(raw["stop_loss"]) if raw.get("stop_loss") is not None else None,
            created_at=_dt_from_ms(raw.get("processed_ms", 0)),
        )

    async def open_positions_async(self) -> list[Position]:
        """Return currently open positions for the configured funded account."""
        dashboard = await self._fetch_dashboard()

        positions_section = dashboard.get("positions")
        if not isinstance(positions_section, dict):
            return []

        raw_positions = positions_section.get("positions", [])
        if not isinstance(raw_positions, list):
            return []

        result: list[Position] = []
        for raw in raw_positions:
            if not isinstance(raw, dict):
                continue
            mapped = self._map_position(raw)
            if mapped is not None:
                result.append(mapped)
        return result

    def open_positions(self) -> list[Position] | Coroutine[Any, Any, list[Position]]:
        """Return open positions synchronously or asynchronously."""
        return _sync_or_async(self.open_positions_async())

    async def open_orders_async(self) -> list[Order]:
        """Return currently open orders for the configured funded account."""
        dashboard = await self._fetch_dashboard()

        raw_orders = dashboard.get("limit_orders")
        if not isinstance(raw_orders, list):
            return []

        result: list[Order] = []
        for raw in raw_orders:
            if not isinstance(raw, dict):
                continue
            result.append(self._map_order(raw))
        return result

    def open_orders(self) -> list[Order] | Coroutine[Any, Any, list[Order]]:
        """Return open orders synchronously or asynchronously."""
        return _sync_or_async(self.open_orders_async())
