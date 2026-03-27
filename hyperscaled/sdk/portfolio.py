"""Positions, orders, and account info SDK interface."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal, TypeVar

import httpx

from hyperscaled.exceptions import HyperscaledError
from hyperscaled.models.trading import ClosedPosition, Order, Position
from hyperscaled.sdk.client import _run_sync

if TYPE_CHECKING:
    from hyperscaled.sdk.client import HyperscaledClient

T = TypeVar("T")

_HL_DASHBOARD_PATH = "/hl-traders/{hl_address}"


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


def _normalize_compact_position(compact: dict[str, Any], account_size: float) -> dict[str, Any]:
    """Expand an abbreviated dashboard position blob into the legacy field layout.

    The new ``get_hl_trader`` response uses compact keys (``tp``, ``t``,
    ``ap``, …).  This converts them to full field names that
    ``_map_position`` / ``_map_closed_position`` expect.
    """
    ap = Decimal(str(compact.get("ap", 0) or 0))
    nl = Decimal(str(compact.get("nl", 0) or 0))
    r = Decimal(str(compact.get("r", 1.0) or 1.0))
    rp = compact.get("rp", 0) or 0
    acct = Decimal(str(account_size))

    net_value = abs(nl * acct) if nl and acct else Decimal(0)
    net_quantity = abs(net_value / ap) if ap else Decimal(0)
    entry_value = net_quantity * ap
    unrealized_pnl = (r - 1) * entry_value if entry_value else Decimal(0)

    # Expand filled orders so _extract_tp_sl can find TP/SL values
    orders: list[dict[str, Any]] = []
    fo = compact.get("fo", {})
    if isinstance(fo, dict):
        for order_data in fo.values():
            if isinstance(order_data, dict):
                orders.append({
                    "take_profit": order_data.get("tk"),
                    "stop_loss": order_data.get("sl"),
                })

    return {
        "trade_pair": compact.get("tp", ""),
        "position_type": compact.get("t", "FLAT"),
        "is_closed_position": "c" in compact,
        "net_quantity": net_quantity,
        "net_value": net_value,
        "average_entry_price": ap,
        "unrealized_pnl": unrealized_pnl,
        "open_ms": compact.get("o", 0),
        "close_ms": compact.get("c", 0),
        "current_return": r,
        "return_at_close": compact.get("rc", 1.0),
        "net_leverage": nl,
        "realized_pnl": rp,
        "orders": orders,
        "unfilled_orders": [],
    }


def _positions_list(
    dashboard: dict[str, Any],
) -> list[dict[str, Any]]:
    """Extract positions as a flat list, handling both old and new formats."""
    positions_section = dashboard.get("positions")
    if not isinstance(positions_section, dict):
        return []

    raw = positions_section.get("positions", {})

    # New format: dict keyed by position_uuid with abbreviated keys
    if isinstance(raw, dict):
        sub_info = dashboard.get("subaccount_info", {})
        account_size = float(
            sub_info.get("account_size", 0) if isinstance(sub_info, dict) else 0
        )
        return [
            _normalize_compact_position(pos, account_size)
            for pos in raw.values()
            if isinstance(pos, dict)
        ]

    # Legacy format: plain list of position dicts
    if isinstance(raw, list):
        return [p for p in raw if isinstance(p, dict)]

    return []


class PortfolioClient:
    """Read-only portfolio visibility for open positions and open orders."""

    def __init__(self, client: HyperscaledClient) -> None:
        self._client = client

    def _resolve_wallet(self) -> str:
        return self._client.resolve_hl_wallet_address()

    async def _fetch_dashboard(self) -> dict[str, Any]:
        hl_address = self._resolve_wallet()
        path = _HL_DASHBOARD_PATH.format(hl_address=hl_address)

        try:
            response = await self._client.validator_http.get(path)
        except httpx.HTTPError as exc:
            raise HyperscaledError(f"Failed to fetch validator dashboard: {exc}") from exc

        if response.status_code == 404:
            raise HyperscaledError(
                f"No validator dashboard for Hyperliquid wallet {hl_address}. "
                "That usually means this address is not registered with the validator yet, "
                "or HYPERSCALED_VALIDATOR_API_URL points at the wrong host. "
                "If you use HYPERSCALED_HL_PRIVATE_KEY only, ensure it matches the wallet "
                "you registered; otherwise set HYPERSCALED_HL_ADDRESS to that registered address."
            )

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HyperscaledError(
                "Failed to fetch validator dashboard: "
                f"{exc.response.status_code} {exc.response.reason_phrase}"
            ) from exc

        payload = response.json()
        if (
            not isinstance(payload, dict)
            or payload.get("status") != "success"
            or "dashboard" not in payload
        ):
            raise HyperscaledError("Validator dashboard response has unexpected shape")
        return payload["dashboard"]

    async def _fetch_hl_clearinghouse(self) -> dict[str, Any]:
        """Fetch the full HL clearinghouse state for the configured wallet."""
        hl_address = self._resolve_wallet()
        hl_info_url = self._client.config.hl_info_url
        try:
            response = await self._client.http.post(
                hl_info_url,
                json={"type": "clearinghouseState", "user": hl_address},
            )
            response.raise_for_status()
        except httpx.HTTPError:
            return {}

        data = response.json()
        if not isinstance(data, dict):
            return {}
        return data

    async def _fetch_hl_positions(self) -> dict[str, dict[str, Any]]:
        """Fetch current positions from the HL clearinghouse for mark/liq prices."""
        data = await self._fetch_hl_clearinghouse()
        positions = data.get("assetPositions", [])
        if not isinstance(positions, list):
            return {}

        result: dict[str, dict[str, Any]] = {}
        for pos in positions:
            p = pos.get("position", {}) if isinstance(pos, dict) else {}
            coin = p.get("coin", "")
            if coin:
                # Derive mark price from positionValue / szi when possible
                mark_price: Decimal | None = None
                szi = p.get("szi")
                position_value = p.get("positionValue")
                if szi is not None and position_value is not None:
                    try:
                        szi_dec = Decimal(str(szi))
                        pv_dec = Decimal(str(position_value))
                        if szi_dec != 0:
                            mark_price = abs(pv_dec / szi_dec)
                    except Exception:
                        pass

                liq_px = p.get("liquidationPx")
                result[coin] = {
                    "mark_price": mark_price,
                    "liquidation_price": _decimal(liq_px) if liq_px is not None else None,
                }
        return result

    def _map_position(
        self,
        raw: dict[str, Any],
        hl_data: dict[str, dict[str, Any]] | None = None,
    ) -> Position | None:
        """Map a validator position dict to an SDK Position, or None to skip."""
        if raw.get("is_closed_position"):
            return None

        position_type = str(raw.get("position_type", "")).upper()
        if position_type == "FLAT":
            return None

        side = "long" if position_type == "LONG" else "short"
        take_profit, stop_loss = _extract_tp_sl(raw)

        symbol = _normalize_trade_pair(raw.get("trade_pair"))

        # Resolve mark_price and liquidation_price from HL data if available.
        # The symbol is e.g. "BTC-USDC"; the HL key is the base coin e.g. "BTC".
        mark_price: Decimal | None = None
        liquidation_price: Decimal | None = None
        if hl_data:
            hl_coin = symbol.split("-")[0] if "-" in symbol else symbol
            coin_data = hl_data.get(hl_coin)
            if coin_data:
                mark_price = coin_data.get("mark_price")
                liquidation_price = coin_data.get("liquidation_price")

        return Position(
            symbol=symbol,
            side=side,
            size=_decimal(raw.get("net_quantity")),
            position_value=_decimal(raw.get("net_value")),
            entry_price=_decimal(raw.get("average_entry_price")),
            mark_price=mark_price,
            liquidation_price=liquidation_price,
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
            limit_price=_decimal(raw["limit_price"])
            if raw.get("limit_price") is not None
            else None,
            fill_price=None,
            scaling_ratio=None,
            take_profit=_decimal(raw["take_profit"])
            if raw.get("take_profit") is not None
            else None,
            stop_loss=_decimal(raw["stop_loss"]) if raw.get("stop_loss") is not None else None,
            created_at=_dt_from_ms(raw.get("processed_ms", 0)),
        )

    async def open_positions_async(self) -> list[Position]:
        """Return currently open positions for the configured funded account."""
        dashboard, hl_positions = await asyncio.gather(
            self._fetch_dashboard(),
            self._fetch_hl_positions(),
        )

        raw_positions = _positions_list(dashboard)

        result: list[Position] = []
        for raw in raw_positions:
            mapped = self._map_position(raw, hl_data=hl_positions)
            if mapped is not None:
                result.append(mapped)
        return result

    def open_positions(self) -> list[Position] | Coroutine[Any, Any, list[Position]]:
        """Return open positions synchronously or asynchronously."""
        return _sync_or_async(self.open_positions_async())

    # ── Exchange (Hyperliquid) positions ──────────────────────────

    def _map_exchange_position(self, raw: dict[str, Any]) -> Position | None:
        """Map a Hyperliquid clearinghouse assetPosition to an SDK Position."""
        p = raw.get("position", {}) if isinstance(raw, dict) else {}
        coin = p.get("coin", "")
        if not coin:
            return None

        szi = p.get("szi")
        if szi is None:
            return None
        szi_dec = _decimal(szi)
        if szi_dec == 0:
            return None  # flat / no position

        side: Literal["long", "short"] = "long" if szi_dec > 0 else "short"
        size = abs(szi_dec)

        position_value = _decimal(p.get("positionValue"))
        entry_price = _decimal(p.get("entryPx"))
        unrealized_pnl = _decimal(p.get("unrealizedPnl"))

        mark_price: Decimal | None = None
        if size != 0 and position_value != 0:
            mark_price = abs(position_value / size)

        liq_px = p.get("liquidationPx")
        liquidation_price = _decimal(liq_px) if liq_px is not None else None

        symbol = f"{coin.upper()}-USDC"

        return Position(
            symbol=symbol,
            side=side,
            size=size,
            position_value=abs(position_value),
            entry_price=entry_price,
            mark_price=mark_price,
            liquidation_price=liquidation_price,
            unrealized_pnl=unrealized_pnl,
            take_profit=None,
            stop_loss=None,
            open_time=datetime.now(tz=timezone.utc),  # HL doesn't expose open time
        )

    async def exchange_positions_async(self) -> list[Position]:
        """Return open positions as reported by the Hyperliquid exchange.

        These come directly from Hyperliquid's clearinghouse state and
        represent what is actually on-exchange, independent of how the
        Vanta Network validator tracks them.
        """
        data = await self._fetch_hl_clearinghouse()
        asset_positions = data.get("assetPositions", [])
        if not isinstance(asset_positions, list):
            return []

        result: list[Position] = []
        for raw in asset_positions:
            mapped = self._map_exchange_position(raw)
            if mapped is not None:
                result.append(mapped)
        return result

    def exchange_positions(self) -> list[Position] | Coroutine[Any, Any, list[Position]]:
        """Return Hyperliquid exchange positions synchronously or asynchronously."""
        return _sync_or_async(self.exchange_positions_async())

    def _map_hl_order(self, raw: dict[str, Any]) -> Order:
        """Map a Hyperliquid info API open-order dict to an SDK Order.

        The HL ``open_orders`` response returns dicts like::

            {"coin": "BTC", "limitPx": "67000.0", "oid": 123456,
             "side": "B", "sz": "0.001", "timestamp": 1710000000000}
        """
        coin = str(raw.get("coin", ""))
        pair = f"{coin.upper()}-USDC" if coin else "UNKNOWN"
        side: str = "long" if raw.get("side") in ("B", "Buy", "buy") else "short"

        return Order(
            order_id=str(raw["oid"]) if raw.get("oid") is not None else None,
            hl_order_id=str(raw["oid"]) if raw.get("oid") is not None else None,
            pair=pair,
            side=side,
            size=_decimal(raw.get("sz")),
            funded_equivalent_size=None,
            order_type="limit",
            status="open",
            limit_price=_decimal(raw.get("limitPx")),
            fill_price=None,
            scaling_ratio=None,
            take_profit=None,
            stop_loss=None,
            created_at=_dt_from_ms(raw.get("timestamp", 0)),
        )

    async def open_orders_async(self) -> list[Order]:
        """Return currently open orders by querying the Hyperliquid API directly."""
        hl_address = self._resolve_wallet()
        hl_info_url = self._client.config.hl_info_url

        try:
            response = await self._client.http.post(
                hl_info_url,
                json={"type": "openOrders", "user": hl_address},
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HyperscaledError(
                f"Hyperliquid open-orders request failed: "
                f"{exc.response.status_code} {exc.response.reason_phrase}"
            ) from exc
        except httpx.HTTPError as exc:
            raise HyperscaledError(f"Hyperliquid open-orders request failed: {exc}") from exc

        raw_orders = response.json()
        if not isinstance(raw_orders, list):
            return []

        result: list[Order] = []
        for raw in raw_orders:
            if not isinstance(raw, dict):
                continue
            result.append(self._map_hl_order(raw))
        return result

    def open_orders(self) -> list[Order] | Coroutine[Any, Any, list[Order]]:
        """Return open orders synchronously or asynchronously."""
        return _sync_or_async(self.open_orders_async())

    # ── Closed position mapping ───────────────────────────────────

    def _map_closed_position(self, raw: dict[str, Any]) -> ClosedPosition | None:
        """Map a validator position dict with is_closed_position=True to ClosedPosition."""
        if not raw.get("is_closed_position"):
            return None

        position_type = str(raw.get("position_type", "")).upper()
        side = "long" if position_type == "LONG" else "short"
        take_profit, stop_loss = _extract_tp_sl(raw)
        symbol = _normalize_trade_pair(raw.get("trade_pair"))

        # realized_pnl: use the explicit field if present, otherwise derive
        # from return_at_close relative to cumulative_entry_value.
        realized_pnl_raw = raw.get("realized_pnl")
        if realized_pnl_raw is not None and Decimal(str(realized_pnl_raw)) != 0:
            realized_pnl = _decimal(realized_pnl_raw)
        else:
            # return_at_close is a multiplier (e.g. 1.05 = +5%).
            # PnL = (return_at_close - 1) * cumulative_entry_value
            return_at_close = raw.get("return_at_close", 1.0)
            entry_value = raw.get("cumulative_entry_value", raw.get("net_value", 0))
            realized_pnl = _decimal(
                Decimal(str(return_at_close)) * _decimal(entry_value) - _decimal(entry_value)
            )

        close_ms = raw.get("close_ms", 0)

        return ClosedPosition(
            symbol=symbol,
            side=side,
            size=_decimal(raw.get("net_quantity")),
            position_value=_decimal(raw.get("net_value")),
            entry_price=_decimal(raw.get("average_entry_price")),
            mark_price=None,
            liquidation_price=None,
            unrealized_pnl=Decimal("0"),
            take_profit=take_profit,
            stop_loss=stop_loss,
            open_time=_dt_from_ms(raw.get("open_ms", 0)),
            realized_pnl=realized_pnl,
            close_time=_dt_from_ms(close_ms),
        )

    # ── Position history ──────────────────────────────────────────

    async def position_history_async(
        self,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        pair: str | None = None,
    ) -> list[ClosedPosition]:
        """Return closed positions from the validator dashboard."""
        dashboard = await self._fetch_dashboard()

        raw_positions = _positions_list(dashboard)

        result: list[ClosedPosition] = []
        for raw in raw_positions:
            mapped = self._map_closed_position(raw)
            if mapped is None:
                continue

            # Date-range filtering on close_time
            if from_date is not None:
                from_dt = from_date if from_date.tzinfo else from_date.replace(tzinfo=timezone.utc)
                if mapped.close_time < from_dt:
                    continue
            if to_date is not None:
                to_dt = to_date if to_date.tzinfo else to_date.replace(tzinfo=timezone.utc)
                if mapped.close_time > to_dt:
                    continue

            # Pair filtering
            if pair is not None and mapped.symbol.upper() != pair.upper():
                continue

            result.append(mapped)

        return result

    def position_history(
        self,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        pair: str | None = None,
    ) -> list[ClosedPosition] | Coroutine[Any, Any, list[ClosedPosition]]:
        """Return closed positions synchronously or asynchronously."""
        return _sync_or_async(
            self.position_history_async(from_date=from_date, to_date=to_date, pair=pair)
        )

    # ── Order history ─────────────────────────────────────────────

    def _map_hl_fill(self, raw: dict[str, Any]) -> Order:
        """Map a Hyperliquid userFills entry to a filled SDK Order."""
        coin = str(raw.get("coin", ""))
        pair = f"{coin.upper()}-USDC" if coin else "UNKNOWN"
        side: str = "long" if raw.get("side") in ("B", "Buy", "buy") else "short"

        return Order(
            order_id=str(raw["oid"]) if raw.get("oid") is not None else None,
            hl_order_id=str(raw["oid"]) if raw.get("oid") is not None else None,
            pair=pair,
            side=side,
            size=_decimal(raw.get("sz")),
            funded_equivalent_size=None,
            order_type="market",
            status="filled",
            limit_price=None,
            fill_price=_decimal(raw.get("px")),
            scaling_ratio=None,
            take_profit=None,
            stop_loss=None,
            created_at=_dt_from_ms(raw.get("time", 0)),
        )

    async def order_history_async(
        self,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        pair: str | None = None,
    ) -> list[Order]:
        """Return historical filled orders from the Hyperliquid API."""
        hl_address = self._resolve_wallet()
        hl_info_url = self._client.config.hl_info_url

        # Use userFillsByTime if date range is provided, otherwise userFills.
        if from_date is not None or to_date is not None:
            start_ms = int(from_date.timestamp() * 1000) if from_date is not None else 0
            end_ms = (
                int(to_date.timestamp() * 1000)
                if to_date is not None
                else int(datetime.now(tz=timezone.utc).timestamp() * 1000)
            )
            request_body: dict[str, Any] = {
                "type": "userFillsByTime",
                "user": hl_address,
                "startTime": start_ms,
                "endTime": end_ms,
            }
        else:
            request_body = {"type": "userFills", "user": hl_address}

        try:
            response = await self._client.http.post(hl_info_url, json=request_body)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HyperscaledError(
                f"Hyperliquid order-history request failed: "
                f"{exc.response.status_code} {exc.response.reason_phrase}"
            ) from exc
        except httpx.HTTPError as exc:
            raise HyperscaledError(f"Hyperliquid order-history request failed: {exc}") from exc

        raw_fills = response.json()
        if not isinstance(raw_fills, list):
            return []

        result: list[Order] = []
        for raw in raw_fills:
            if not isinstance(raw, dict):
                continue
            order = self._map_hl_fill(raw)

            # Pair filtering
            if pair is not None and order.pair.upper() != pair.upper():
                continue

            result.append(order)

        return result

    def order_history(
        self,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        pair: str | None = None,
    ) -> list[Order] | Coroutine[Any, Any, list[Order]]:
        """Return filled orders synchronously or asynchronously."""
        return _sync_or_async(
            self.order_history_async(from_date=from_date, to_date=to_date, pair=pair)
        )
