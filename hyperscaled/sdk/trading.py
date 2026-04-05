"""Trade submission SDK interface.

Submits orders to Hyperliquid via ``hyperliquid-python-sdk`` and translates
the results into funded-account equivalents using the scaling ratio.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Coroutine
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any, TypeVar

import httpx

from hyperscaled.exceptions import HyperscaledError, InsufficientBalanceError
from hyperscaled.models.account import MINIMUM_BALANCE
from hyperscaled.models.trading import Order
from hyperscaled.sdk.pairs import SUPPORTED_PAIRS, normalize_pair_to_hl

if TYPE_CHECKING:
    from hyperscaled.sdk.client import HyperscaledClient

T = TypeVar("T")


def _sync_or_async(coro: Coroutine[Any, Any, T]) -> T | Coroutine[Any, Any, T]:
    """Run sync when possible, otherwise return the coroutine for awaiting."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        return coro

    from hyperscaled.sdk.client import _run_sync

    result: T = _run_sync(coro)
    return result


class TradingClient:
    """Submit orders to Hyperliquid and translate to funded-account equivalents."""

    def __init__(self, client: HyperscaledClient) -> None:
        self._client = client
        self._exchange: Any = None
        self._info: Any = None
        self._trailing_state: dict[str, dict[str, Any]] = {}

    def _get_exchange(self) -> Any:
        """Lazy-initialize the HL Exchange from the configured private key."""
        if self._exchange is None:
            try:
                from eth_account import Account
                from hyperliquid.exchange import Exchange
            except ImportError as exc:
                raise HyperscaledError(
                    "hyperliquid-python-sdk is not installed. "
                    "Install with: pip install 'hyperliquid-python-sdk>=0.4'"
                ) from exc

            private_key = self._client._resolve_hl_private_key()
            try:
                wallet = Account.from_key(private_key)
            except Exception as exc:
                raise HyperscaledError(
                    f"Invalid Hyperliquid private key: {type(exc).__name__}"
                ) from exc

            base_url = self._client.config.hl_base_url if self._client.config.api.testnet else None

            # When the private key belongs to an API wallet (agent), the main
            # account address must be passed explicitly so that position lookups
            # (e.g. market_close) query the right account.
            main_address = (self._client.config.wallet.hl_address or "").strip() or None
            api_address = wallet.address
            account_address = main_address if main_address and main_address.lower() != api_address.lower() else None

            # Pass empty spot_meta to avoid IndexError in hyperliquid-python-sdk
            # spot metadata parsing — we only need perp trading functionality.
            self._exchange = Exchange(
                wallet=wallet,
                base_url=base_url,
                spot_meta={"universe": [], "tokens": []},
                account_address=account_address,
            )
        return self._exchange

    def _get_info(self) -> Any:
        """Lazy-initialize the HL Info client for open-order discovery."""
        if self._info is None:
            try:
                from hyperliquid.info import Info
            except ImportError as exc:
                raise HyperscaledError(
                    "hyperliquid-python-sdk is not installed. "
                    "Install with: pip install 'hyperliquid-python-sdk>=0.4'"
                ) from exc
            base_url = self._client.config.hl_base_url if self._client.config.api.testnet else None
            # Pass empty spot_meta to avoid IndexError in hyperliquid-python-sdk
            # spot metadata parsing — we only need perp trading functionality.
            self._info = Info(
                base_url=base_url, skip_ws=True, spot_meta={"universe": [], "tokens": []}
            )
        return self._info

    def _resolve_wallet(self) -> str:
        """Return the HL wallet address required for order lookups."""
        return self._client.resolve_hl_wallet_address()

    async def _fetch_sz_decimals(self, hl_name: str) -> int:
        """Fetch the szDecimals for a perp asset from Hyperliquid metadata."""
        hl_info_url = self._client.config.hl_info_url
        try:
            response = await self._client.http.post(hl_info_url, json={"type": "meta"})
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise HyperscaledError(f"Hyperliquid meta request failed: {exc}") from exc

        payload = response.json()
        for asset in payload.get("universe", []):
            if asset.get("name") == hl_name:
                return int(asset.get("szDecimals", 0))
        raise HyperscaledError(f"Asset {hl_name} not found in Hyperliquid metadata")

    @staticmethod
    def _round_size(size: Decimal, sz_decimals: int) -> Decimal:
        """Round size down to the asset's allowed precision."""
        if sz_decimals == 0:
            return size.to_integral_value(rounding="ROUND_DOWN")
        quant = Decimal(10) ** -sz_decimals
        return size.quantize(quant, rounding="ROUND_DOWN")

    async def _fetch_mid_price(self, hl_name: str) -> Decimal:
        """Fetch the current Hyperliquid mid price for a coin."""
        hl_info_url = self._client.config.hl_info_url
        try:
            response = await self._client.http.post(hl_info_url, json={"type": "allMids"})
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HyperscaledError(
                f"Hyperliquid mid-price request failed: {exc.response.status_code}"
            ) from exc
        except httpx.HTTPError as exc:
            raise HyperscaledError(f"Hyperliquid mid-price request failed: {exc}") from exc

        payload = response.json()
        if not isinstance(payload, dict) or hl_name not in payload:
            raise HyperscaledError(f"Hyperliquid mid price unavailable for {hl_name}")
        return Decimal(str(payload[hl_name]))

    @staticmethod
    def _display_pair_from_hl_name(name: str) -> str:
        """Map Hyperliquid asset names back to the SDK pair format when possible."""
        pair = f"{name.upper()}-USDC"
        return pair if pair in SUPPORTED_PAIRS else name.upper()

    # Number of decimal places the exchange accepts for trigger prices.
    # Validated against live exchange behavior (spike 2026-03-31).
    TRIGGER_PRICE_DECIMALS: dict[str, int] = {
        "BTC": 0,
        "ETH": 1,
        "SOL": 2,
        "XRP": 4,
        "DOGE": 5,
        "ADA": 4,
    }

    def _round_trigger_price(self, hl_name: str, price: Decimal) -> Decimal:
        """Round a trigger price to the asset's accepted price tick."""
        decimals = self.TRIGGER_PRICE_DECIMALS.get(hl_name)
        if decimals is None:
            raise HyperscaledError(
                f"No trigger price precision defined for {hl_name}. "
                f"Add the asset to TRIGGER_PRICE_DECIMALS after verifying "
                f"the exchange's accepted tick size."
            )
        if decimals == 0:
            return price.quantize(Decimal("1"), rounding="ROUND_HALF_UP")
        quant = Decimal(10) ** -decimals
        return price.quantize(quant, rounding="ROUND_HALF_UP")

    @staticmethod
    def _validate_trailing_stop(trailing_stop: dict[str, Any]) -> None:
        """Validate trailing_stop dict shape and ranges."""
        if not isinstance(trailing_stop, dict):
            raise ValueError("trailing_stop must be a dict")

        has_percent = "trailing_percent" in trailing_stop
        has_value = "trailing_value" in trailing_stop

        if has_percent == has_value:
            raise ValueError(
                "trailing_stop must contain exactly one of "
                "'trailing_percent' or 'trailing_value'"
            )

        if has_percent:
            pct = float(trailing_stop["trailing_percent"])
            if not (0 < pct < 1):
                raise ValueError(
                    f"trailing_percent must be between 0 and 1 (exclusive), got {pct}"
                )

        if has_value:
            val = float(trailing_stop["trailing_value"])
            if val <= 0:
                raise ValueError(f"trailing_value must be greater than 0, got {val}")

    @staticmethod
    def _validate_tp_sl_prices(
        side: str,
        take_profit: Decimal | None,
        stop_loss: Decimal | None,
        reference_price: Decimal,
    ) -> None:
        """Validate TP/SL price relationships against entry/fill price."""
        if side == "long":
            if stop_loss is not None and stop_loss >= reference_price:
                raise ValueError(
                    f"LONG stop_loss ({stop_loss}) must be below "
                    f"entry/fill price ({reference_price})"
                )
            if take_profit is not None and take_profit <= reference_price:
                raise ValueError(
                    f"LONG take_profit ({take_profit}) must be above "
                    f"entry/fill price ({reference_price})"
                )
        else:
            if stop_loss is not None and stop_loss <= reference_price:
                raise ValueError(
                    f"SHORT stop_loss ({stop_loss}) must be above "
                    f"entry/fill price ({reference_price})"
                )
            if take_profit is not None and take_profit >= reference_price:
                raise ValueError(
                    f"SHORT take_profit ({take_profit}) must be below "
                    f"entry/fill price ({reference_price})"
                )

    @staticmethod
    def _compute_trailing_sl(
        side: str,
        reference_price: Decimal,
        trailing_stop: dict[str, Any],
        fixed_sl: Decimal | None = None,
    ) -> Decimal:
        """Compute the effective SL price from trailing parameters.

        For LONG: SL = reference_price * (1 - pct) or reference_price - value.
        For SHORT: SL = reference_price * (1 + pct) or reference_price + value.
        If fixed_sl is also provided, use the more protective value.
        """
        trailing_percent = trailing_stop.get("trailing_percent")
        trailing_value = trailing_stop.get("trailing_value")

        if trailing_percent is not None:
            pct = Decimal(str(trailing_percent))
            if side == "long":
                trailing_sl = reference_price * (1 - pct)
            else:
                trailing_sl = reference_price * (1 + pct)
        else:
            val = Decimal(str(trailing_value))
            if side == "long":
                trailing_sl = reference_price - val
            else:
                trailing_sl = reference_price + val

        if fixed_sl is not None:
            if side == "long":
                return max(fixed_sl, trailing_sl)
            else:
                return min(fixed_sl, trailing_sl)

        return trailing_sl

    def _build_trigger_order_request(
        self,
        hl_name: str,
        is_buy: bool,
        sz: float,
        trigger_px: float,
        tpsl: str,
    ) -> dict[str, Any]:
        """Build an HL OrderRequest dict for a trigger order."""
        return {
            "coin": hl_name,
            "is_buy": is_buy,
            "sz": sz,
            "limit_px": trigger_px,
            "order_type": {
                "trigger": {"triggerPx": trigger_px, "isMarket": True, "tpsl": tpsl}
            },
            "reduce_only": True,
        }

    async def _place_tp_sl_triggers(
        self,
        hl_name: str,
        parent_is_buy: bool,
        filled_sz: float,
        take_profit: Decimal | None,
        stop_loss: Decimal | None,
    ) -> tuple[str | None, str | None, str, str | None]:
        """Place TP/SL trigger orders and return (tp_oid, sl_oid, status, error)."""
        exchange = self._get_exchange()
        close_is_buy = not parent_is_buy

        tp_px = (
            float(self._round_trigger_price(hl_name, take_profit))
            if take_profit is not None
            else None
        )
        sl_px = (
            float(self._round_trigger_price(hl_name, stop_loss))
            if stop_loss is not None
            else None
        )

        requests: list[dict[str, Any]] = []
        tp_idx: int | None = None
        sl_idx: int | None = None

        if tp_px is not None:
            tp_idx = len(requests)
            requests.append(
                self._build_trigger_order_request(hl_name, close_is_buy, filled_sz, tp_px, "tp")
            )

        if sl_px is not None:
            sl_idx = len(requests)
            requests.append(
                self._build_trigger_order_request(hl_name, close_is_buy, filled_sz, sl_px, "sl")
            )

        if not requests:
            return None, None, "failed", "No TP/SL trigger requests were built"

        is_grouped = len(requests) > 1

        # Record timestamp BEFORE the exchange call so that exchange-assigned
        # order timestamps (which are set when the exchange receives the
        # request, before we get the response) fall within the recency window.
        # Subtract 2 seconds as buffer for network latency and clock skew.
        pre_placement_ts = int(time.time() * 1000) - 2_000

        if not is_grouped:
            request = requests[0]
            result = await asyncio.to_thread(
                exchange.order,
                request["coin"],
                request["is_buy"],
                request["sz"],
                request["limit_px"],
                request["order_type"],
                request["reduce_only"],
            )
        else:
            result = await asyncio.to_thread(
                exchange.bulk_orders, requests, None, "positionTpsl"
            )

        return await self._parse_trigger_response(
            result, tp_idx, sl_idx, is_grouped, hl_name, tp_px, sl_px, filled_sz,
            pre_placement_ts,
        )

    async def _parse_trigger_response(
        self,
        result: dict[str, Any],
        tp_idx: int | None,
        sl_idx: int | None,
        is_grouped: bool,
        hl_name: str,
        tp_px: float | None,
        sl_px: float | None,
        filled_sz: float,
        pre_placement_ts_ms: int | None = None,
    ) -> tuple[str | None, str | None, str, str | None]:
        """Extract trigger order IDs plus placement status from the HL response."""
        if result.get("status") != "ok":
            return (
                None,
                None,
                "failed",
                f"Hyperliquid trigger placement failed: {result.get('status', 'unknown')}",
            )

        try:
            statuses = result["response"]["data"]["statuses"]
        except (KeyError, TypeError):
            return None, None, "failed", "Unexpected Hyperliquid trigger response shape"

        tp_oid: str | None = None
        sl_oid: str | None = None
        errors: list[str] = []
        needs_frontend_lookup = False

        for label, tgt_idx in [("TP", tp_idx), ("SL", sl_idx)]:
            if tgt_idx is None or tgt_idx >= len(statuses):
                continue
            entry = statuses[tgt_idx]
            if isinstance(entry, dict) and "resting" in entry:
                oid = str(entry["resting"]["oid"])
                if label == "TP":
                    tp_oid = oid
                else:
                    sl_oid = oid
            elif isinstance(entry, dict) and "error" in entry:
                errors.append(f"{label}: {entry['error']}")
            elif entry == "waitingForTrigger":
                needs_frontend_lookup = True
            else:
                errors.append(f"{label}: unexpected status entry: {entry}")

        # Grouped positionTpsl orders return "waitingForTrigger" — resolve OIDs
        # via frontend_open_orders() using multi-field matching.
        if needs_frontend_lookup and not errors:
            placement_ts = (
                pre_placement_ts_ms
                if pre_placement_ts_ms is not None
                else int(time.time() * 1000) - 2_000
            )
            for _attempt in range(3):
                tp_oid, sl_oid = await self._resolve_trigger_oids_from_frontend(
                    hl_name, tp_px, sl_px, filled_sz, placement_ts,
                )
                if (tp_px is None or tp_oid) and (sl_px is None or sl_oid):
                    break
                await asyncio.sleep(0.5)

            if tp_px is not None and tp_oid is None:
                errors.append(
                    "TP: placed (waitingForTrigger) but OID not found in "
                    "frontend_open_orders after 3 attempts"
                )
            if sl_px is not None and sl_oid is None:
                errors.append(
                    "SL: placed (waitingForTrigger) but OID not found in "
                    "frontend_open_orders after 3 attempts"
                )

        if (tp_oid or sl_oid) and not errors:
            return tp_oid, sl_oid, "placed", None

        if (tp_oid or sl_oid) and errors:
            return tp_oid, sl_oid, "partial_failure", "; ".join(errors)

        error_message = "; ".join(errors) if errors else "No TP/SL trigger orders were accepted"
        return None, None, "failed", error_message

    async def _resolve_trigger_oids_from_frontend(
        self,
        hl_name: str,
        tp_px: float | None,
        sl_px: float | None,
        expected_sz: float,
        placement_ts_ms: int,
    ) -> tuple[str | None, str | None]:
        """Resolve TP/SL OIDs from frontend_open_orders() after grouped placement.

        Uses multi-field matching (isPositionTpsl is unreliable per spike).
        """
        wallet = self._resolve_wallet()
        info = self._get_info()
        try:
            frontend = await asyncio.to_thread(info.frontend_open_orders, wallet)
        except Exception as exc:
            raise HyperscaledError(
                f"Failed to resolve trigger OIDs via frontend_open_orders: {exc}"
            ) from exc

        recency_window_ms = 5_000
        expected_sz_str = str(expected_sz)
        tp_px_str = str(tp_px) if tp_px is not None else None
        sl_px_str = str(sl_px) if sl_px is not None else None

        candidates: list[dict[str, Any]] = []
        for order in frontend:
            if order.get("coin") != hl_name:
                continue
            if not order.get("isTrigger"):
                continue
            if not order.get("reduceOnly"):
                continue
            order_ts = int(order.get("timestamp", 0))
            if order_ts < placement_ts_ms or order_ts > placement_ts_ms + recency_window_ms:
                continue
            candidates.append(order)

        tp_oid: str | None = None
        sl_oid: str | None = None
        tp_candidates: list[dict[str, Any]] = []
        sl_candidates: list[dict[str, Any]] = []

        for order in candidates:
            order_type = str(order.get("orderType", ""))
            order_trigger_px = str(order.get("triggerPx", ""))
            order_sz = str(order.get("sz", ""))

            if tp_px_str is not None and "Take Profit" in order_type:
                if order_trigger_px == tp_px_str and order_sz == expected_sz_str:
                    tp_candidates.append(order)

            if sl_px_str is not None and "Stop" in order_type:
                if order_trigger_px == sl_px_str and order_sz == expected_sz_str:
                    sl_candidates.append(order)

        # Prefer the pair sharing the exact same timestamp (grouped orders).
        if tp_candidates and sl_candidates and tp_px_str and sl_px_str:
            for tc in tp_candidates:
                for sc in sl_candidates:
                    if tc.get("timestamp") == sc.get("timestamp"):
                        return str(tc["oid"]), str(sc["oid"])

        if tp_candidates:
            tp_oid = str(tp_candidates[0]["oid"])
        if sl_candidates:
            sl_oid = str(sl_candidates[0]["oid"])

        return tp_oid, sl_oid

    def _is_tp_sl_trigger_order(self, order: dict[str, Any]) -> bool:
        """Return True for HL trigger orders identifiable as TP/SL."""
        if not order.get("isTrigger"):
            return False
        order_type = str(order.get("orderType", ""))
        return "Take Profit" in order_type or "Stop" in order_type

    async def _find_existing_triggers(self, hl_name: str) -> list[dict[str, Any]]:
        """Return currently open TP/SL trigger orders for a coin."""
        wallet = self._resolve_wallet()
        info = self._get_info()
        try:
            frontend = await asyncio.to_thread(info.frontend_open_orders, wallet)
        except Exception as exc:
            raise HyperscaledError(
                f"Failed to discover existing TP/SL trigger orders for {hl_name}: {exc}"
            ) from exc

        return [
            order
            for order in frontend
            if order.get("coin") == hl_name and self._is_tp_sl_trigger_order(order)
        ]

    async def _cancel_trigger_oids(self, orders: list[dict[str, Any]]) -> None:
        """Cancel specific trigger orders by oid. Fail fast on errors.

        Inspects per-order cancel statuses so that partial failures (e.g. one
        order cancelled, another errored) are caught before replacement
        triggers are placed.
        """
        if not orders:
            return

        requests = [
            {"coin": str(order["coin"]), "oid": int(order["oid"])}
            for order in orders
            if order.get("oid") is not None and order.get("coin") is not None
        ]
        if not requests:
            return

        exchange = self._get_exchange()
        try:
            result = await asyncio.to_thread(exchange.bulk_cancel, requests)
        except Exception as exc:
            raise HyperscaledError(
                f"Failed to cancel existing TP/SL trigger orders: {exc}"
            ) from exc

        parsed = self._parse_cancel_response(result, requests)
        failed = [
            entry for entry in parsed
            if entry["status"] not in ("cancelled", "already_closed", "not_found")
        ]
        if failed:
            details = "; ".join(
                f"oid {e['hl_order_id']}: {e['message']}" for e in failed
            )
            raise HyperscaledError(
                f"Partial cancel failure — aborting TP/SL replacement to avoid "
                f"duplicate triggers. Failed cancels: {details}"
            )

    def _register_trailing_state(
        self,
        *,
        hl_name: str,
        side: str,
        best_price: Decimal,
        trailing_stop: dict[str, Any],
        fixed_sl: Decimal | None,
        current_sl_oid: str,
        position_sz: float,
    ) -> None:
        """Record trailing stop state for later ratcheting."""
        self._trailing_state[hl_name] = {
            "side": side,
            "best_price": best_price,
            "trailing_stop": trailing_stop,
            "fixed_sl": fixed_sl,
            "current_sl_oid": current_sl_oid,
            "position_sz": position_sz,
            "degraded": False,
            "last_error": None,
        }

    @staticmethod
    def _parse_order_id(order_id: str) -> int:
        """Parse the string ``hl_order_id`` into the integer HL SDK expects."""
        try:
            return int(order_id)
        except ValueError as exc:
            raise ValueError(
                f"Invalid order_id {order_id!r} — expected a numeric Hyperliquid order ID"
            ) from exc

    async def _fetch_open_orders(self) -> list[dict[str, Any]]:
        """Return currently open orders for the configured wallet."""
        wallet = self._resolve_wallet()
        info = self._get_info()
        try:
            result = await asyncio.to_thread(info.open_orders, wallet)
        except Exception as exc:
            raise HyperscaledError(f"Hyperliquid open-orders request failed: {exc}") from exc
        if not isinstance(result, list):
            raise HyperscaledError("Unexpected Hyperliquid open-orders response shape")
        return result

    async def _pre_validate(
        self,
        pair: str,
        side: str,
        size: Decimal,
        order_type: str,
        price: Decimal | None,
    ) -> None:
        """Run validator-backed pre-submission checks before any HL call."""
        await self._client.rules.validate_trade_async(
            pair=pair,
            side=side,
            size=size,
            order_type=order_type,
            price=price,
        )

    async def submit_async(
        self,
        pair: str,
        side: str,
        size: Decimal,
        order_type: str,
        price: Decimal | None = None,
        take_profit: Decimal | None = None,
        stop_loss: Decimal | None = None,
        size_in_usd: bool = False,
        trailing_stop: dict[str, Any] | None = None,
        leverage: int | None = None,
    ) -> Order:
        """Submit an order and return translated funded-account execution info.

        When *size_in_usd* is ``True``, *size* is interpreted as a USD notional
        value and automatically converted to coin quantity using the current
        Hyperliquid mid price.
        """
        # ── Input validation ──────────────────────────────────
        if not pair.strip():
            raise ValueError("Pair must be a non-empty string")

        if side not in ("long", "short"):
            raise ValueError(f"Invalid side {side!r} — must be 'long' or 'short'")

        if size <= 0:
            raise ValueError(f"Size must be positive, got {size}")

        if order_type not in ("market", "limit"):
            raise ValueError(f"Invalid order_type {order_type!r} — must be 'market' or 'limit'")

        if order_type == "limit" and price is None:
            raise ValueError("Price is required for limit orders")
        if order_type == "market" and price is not None:
            raise ValueError("Price must not be provided for market orders")

        if trailing_stop is not None:
            self._validate_trailing_stop(trailing_stop)

        # ── Funded account size ───────────────────────────────
        funded_account_size = self._client.config.account.funded_account_size
        if funded_account_size <= 0:
            raise HyperscaledError(
                "No funded account size configured. "
                "Complete registration first via `client.register.purchase()` "
                "or set account.funded_account_size in config."
            )

        # ── Local config preconditions ────────────────────────
        _ = self._client._resolve_hl_private_key()

        # ── Normalize pair ────────────────────────────────────
        hl_name = normalize_pair_to_hl(pair)

        # ── USD → coin conversion ─────────────────────────────
        if size_in_usd:
            mid_price = await self._fetch_mid_price(hl_name)
            if mid_price <= 0:
                raise HyperscaledError(f"Invalid mid price for {pair}: {mid_price}")
            coin_size = size / mid_price
        else:
            coin_size = size

        # ── Round to asset precision ──────────────────────────
        sz_decimals = await self._fetch_sz_decimals(hl_name)
        coin_size = self._round_size(coin_size, sz_decimals)
        if coin_size <= 0:
            raise ValueError(
                f"Size too small for {pair} after rounding to {sz_decimals} decimals"
            )

        # ── Pre-validation seam (SDK-012) ─────────────────────
        await self._pre_validate(pair, side, coin_size, order_type, price)

        # ── Live HL balance ───────────────────────────────────
        wallet = self._client.account._resolve_wallet()
        balance_status = await self._client.account.check_balance_async(wallet)
        hl_balance = balance_status.balance
        if hl_balance <= 0:
            network = "testnet" if self._client.config.api.testnet else "mainnet"
            raise HyperscaledError(
                f"Hyperliquid perps account balance is zero or negative "
                f"(wallet={wallet}, network={network}, accountValue={hl_balance}). "
                f"If you have funds in your Hyperliquid spot wallet, transfer USDC "
                f"to perps margin first. Also verify the wallet address and "
                f"network (testnet vs mainnet) are correct."
            )

        # ── Scaling ratio ─────────────────────────────────────
        scaling_ratio = Decimal(str(funded_account_size)) / hl_balance

        is_buy = side == "long"

        # ── Place order via HL SDK ────────────────────────────
        exchange = self._get_exchange()
        try:
            # Set leverage if explicitly requested by the trader.
            # If not provided, HL uses whatever the trader already has configured.
            if leverage is not None:
                lev_result = await asyncio.to_thread(
                    exchange.update_leverage, leverage, hl_name, True
                )
                if isinstance(lev_result, dict) and lev_result.get("status") != "ok":
                    raise HyperscaledError(
                        f"Failed to set {leverage}x leverage for {pair}: {lev_result}"
                    )

            if order_type == "market":
                result = await asyncio.to_thread(
                    exchange.market_open, hl_name, is_buy, float(coin_size)
                )
            else:
                result = await asyncio.to_thread(
                    exchange.order,
                    hl_name, is_buy, float(coin_size), float(price),  # type: ignore[arg-type]
                    {"limit": {"tif": "Gtc"}},
                )
        except Exception as exc:
            raise HyperscaledError(f"Hyperliquid order submission failed: {exc}") from exc

        # ── Parse parent response ─────────────────────────────
        order = self._parse_hl_response(
            result, pair, side, size, order_type, scaling_ratio,
            take_profit, stop_loss, price,
        )

        # ── Place TP/SL trigger orders ────────────────────────
        has_triggers = (
            take_profit is not None or stop_loss is not None or trailing_stop is not None
        )
        parent_filled = order.status in ("filled", "partial")

        if has_triggers and parent_filled and order.fill_price is not None:
            effective_sl = stop_loss

            if trailing_stop is not None:
                effective_sl = self._compute_trailing_sl(
                    side, order.fill_price, trailing_stop, stop_loss,
                )
                order.trailing_stop = trailing_stop

            if take_profit is not None or effective_sl is not None:
                self._validate_tp_sl_prices(side, take_profit, effective_sl, order.fill_price)

            if order.filled_size is None:
                raise HyperscaledError(
                    "Filled order missing filled_size in parsed HL response"
                )
            filled_sz = float(order.filled_size)

            try:
                tp_oid, sl_oid, trigger_status, trigger_error = (
                    await self._place_tp_sl_triggers(
                        hl_name,
                        parent_is_buy=is_buy,
                        filled_sz=filled_sz,
                        take_profit=take_profit,
                        stop_loss=effective_sl,
                    )
                )
                order.tp_order_id = tp_oid
                order.sl_order_id = sl_oid
                order.trigger_status = trigger_status  # type: ignore[assignment]
                order.trigger_error = trigger_error
            except Exception as exc:
                order.trigger_status = "failed"  # type: ignore[assignment]
                order.trigger_error = str(exc)

            if trailing_stop is not None and order.sl_order_id is not None:
                self._register_trailing_state(
                    hl_name=hl_name,
                    side=side,
                    best_price=order.fill_price,
                    trailing_stop=trailing_stop,
                    fixed_sl=stop_loss,
                    current_sl_oid=order.sl_order_id,
                    position_sz=filled_sz,
                )

            if trailing_stop is not None and effective_sl != stop_loss:
                order.stop_loss = effective_sl

        elif has_triggers and order.status == "pending":
            order.trailing_stop = trailing_stop
            order.trigger_status = "pending_parent_fill"  # type: ignore[assignment]

        return order

    def submit(
        self,
        pair: str,
        side: str,
        size: Decimal,
        order_type: str,
        price: Decimal | None = None,
        take_profit: Decimal | None = None,
        stop_loss: Decimal | None = None,
        size_in_usd: bool = False,
        trailing_stop: dict[str, Any] | None = None,
        leverage: int | None = None,
    ) -> Order | Coroutine[Any, Any, Order]:
        """Submit an order (sync or async), following the pattern from AccountClient."""
        return _sync_or_async(
            self.submit_async(
                pair, side, size, order_type, price, take_profit, stop_loss,
                size_in_usd=size_in_usd, trailing_stop=trailing_stop,
                leverage=leverage,
            )
        )

    async def cancel_async(self, order_id: str) -> dict[str, object]:
        """Cancel a single open order by Hyperliquid order ID."""
        oid = self._parse_order_id(order_id)
        open_orders = await self._fetch_open_orders()
        match = next((order for order in open_orders if int(order.get("oid", -1)) == oid), None)

        if match is None:
            return {
                "hl_order_id": order_id,
                "status": "not_found",
                "message": "Order is not currently open or cancellable.",
            }

        exchange = self._get_exchange()
        try:
            result = await asyncio.to_thread(exchange.cancel, str(match["coin"]), oid)
        except Exception as exc:
            raise HyperscaledError(f"Hyperliquid order cancellation failed: {exc}") from exc

        return self._parse_cancel_response(result, [match])[0]

    def cancel(self, order_id: str) -> dict[str, object] | Coroutine[Any, Any, dict[str, object]]:
        """Cancel a single order (sync or async)."""
        return _sync_or_async(self.cancel_async(order_id))

    async def cancel_all_async(self) -> dict[str, object]:
        """Cancel all currently open orders for the configured account."""
        open_orders = await self._fetch_open_orders()
        if not open_orders:
            return {
                "status": "ok",
                "message": "No open orders to cancel.",
                "total_open_orders": 0,
                "cancelled_count": 0,
                "failed_count": 0,
                "results": [],
            }

        exchange = self._get_exchange()
        requests = [
            {"coin": str(order["coin"]), "oid": int(order["oid"])}
            for order in open_orders
        ]
        try:
            result = await asyncio.to_thread(exchange.bulk_cancel, requests)
        except Exception as exc:
            raise HyperscaledError(f"Hyperliquid order cancellation failed: {exc}") from exc

        parsed = self._parse_cancel_response(result, requests)
        cancelled_count = sum(1 for entry in parsed if entry["status"] == "cancelled")
        failed_count = len(parsed) - cancelled_count
        return {
            "status": "ok" if failed_count == 0 else "partial",
            "message": (
                f"Cancelled {cancelled_count} of {len(parsed)} open orders."
                if parsed
                else "No open orders to cancel."
            ),
            "total_open_orders": len(parsed),
            "cancelled_count": cancelled_count,
            "failed_count": failed_count,
            "results": parsed,
        }

    def cancel_all(self) -> dict[str, object] | Coroutine[Any, Any, dict[str, object]]:
        """Cancel all open orders (sync or async)."""
        return _sync_or_async(self.cancel_all_async())

    async def close_async(self, pair: str) -> Order:
        """Market-close the full open position for *pair*.

        Fetches the current position size from Hyperliquid, then submits a
        market order in the opposite direction to fully close it.
        """
        if not pair.strip():
            raise ValueError("Pair must be a non-empty string")

        funded_account_size = self._client.config.account.funded_account_size
        if funded_account_size <= 0:
            raise HyperscaledError(
                "No funded account size configured. "
                "Reconnect with /connect after ensuring you have an active funded account."
            )

        hl_name = normalize_pair_to_hl(pair)

        # Fetch the current position from Hyperliquid clearinghouse
        hl_info_url = self._client.config.hl_info_url
        wallet = self._resolve_wallet()
        try:
            response = await self._client.http.post(
                hl_info_url,
                json={"type": "clearinghouseState", "user": wallet},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise HyperscaledError(f"Failed to fetch positions: {exc}") from exc

        data = response.json()
        asset_positions = data.get("assetPositions", [])
        position = next(
            (
                p["position"]
                for p in asset_positions
                if isinstance(p, dict) and p.get("position", {}).get("coin") == hl_name
            ),
            None,
        )

        if position is None or float(position.get("szi", 0)) == 0:
            raise HyperscaledError(f"No open position found for {pair}.")

        szi = Decimal(str(position["szi"]))
        is_long = szi > 0

        # Close via market_close (handles size + slippage automatically)
        exchange = self._get_exchange()
        try:
            result = await asyncio.to_thread(exchange.market_close, hl_name)
        except Exception as exc:
            raise HyperscaledError(f"Hyperliquid close failed: {exc}") from exc

        if result is None:
            raise HyperscaledError(
                f"Hyperliquid returned no response for close on {pair}. "
                "The position may already be closed."
            )

        # Compute scaling ratio for display
        balance_status = await self._client.account.check_balance_async(wallet)
        scaling_ratio = Decimal(str(funded_account_size)) / balance_status.balance

        # Closing a long is a short order and vice versa
        close_side = "short" if is_long else "long"

        return self._parse_hl_response(
            result,
            pair=pair,
            side=close_side,
            size=abs(szi),
            order_type="market",
            scaling_ratio=scaling_ratio,
            take_profit=None,
            stop_loss=None,
            price=None,
        )

    def close(self, pair: str) -> Order | Coroutine[Any, Any, Order]:
        """Close the full open position for *pair* (sync or async)."""
        return _sync_or_async(self.close_async(pair))

    async def set_tp_sl_async(
        self,
        pair: str,
        take_profit: Decimal | None = None,
        stop_loss: Decimal | None = None,
        trailing_stop: dict[str, Any] | None = None,
    ) -> dict[str, str | None]:
        """Add or replace TP/SL on an existing position.

        Cancels any existing managed TP/SL trigger orders for the pair, then
        places new ones. Returns the new trigger order IDs plus status.
        """
        if take_profit is None and stop_loss is None and trailing_stop is None:
            raise ValueError(
                "At least one of take_profit, stop_loss, or trailing_stop must be provided"
            )

        if trailing_stop is not None:
            self._validate_trailing_stop(trailing_stop)

        hl_name = normalize_pair_to_hl(pair)

        # Fetch current position to determine side and size
        hl_info_url = self._client.config.hl_info_url
        wallet = self._resolve_wallet()
        try:
            response = await self._client.http.post(
                hl_info_url,
                json={"type": "clearinghouseState", "user": wallet},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise HyperscaledError(f"Failed to fetch positions: {exc}") from exc

        data = response.json()
        asset_positions = data.get("assetPositions", [])
        position = next(
            (
                p["position"]
                for p in asset_positions
                if isinstance(p, dict)
                and p.get("position", {}).get("coin") == hl_name
            ),
            None,
        )

        if position is None or float(position.get("szi", 0)) == 0:
            raise HyperscaledError(f"No open position found for {pair}")

        szi = Decimal(str(position["szi"]))
        is_long = szi > 0
        side = "long" if is_long else "short"
        position_sz = abs(float(szi))

        mark_price = await self._fetch_mid_price(hl_name)

        effective_sl = stop_loss
        if trailing_stop is not None:
            effective_sl = self._compute_trailing_sl(side, mark_price, trailing_stop, stop_loss)

        if take_profit is not None or effective_sl is not None:
            self._validate_tp_sl_prices(side, take_profit, effective_sl, mark_price)

        # Cancel existing trigger orders being replaced
        existing = await self._find_existing_triggers(hl_name)
        await self._cancel_trigger_oids(existing)

        tp_oid, sl_oid, trigger_status, trigger_error = await self._place_tp_sl_triggers(
            hl_name,
            parent_is_buy=is_long,
            filled_sz=position_sz,
            take_profit=take_profit,
            stop_loss=effective_sl,
        )

        if trigger_status == "failed":
            raise HyperscaledError(
                trigger_error or "Failed to place TP/SL trigger orders"
            )

        if trailing_stop is not None and sl_oid is not None:
            self._register_trailing_state(
                hl_name=hl_name,
                side=side,
                best_price=mark_price,
                trailing_stop=trailing_stop,
                fixed_sl=stop_loss,
                current_sl_oid=sl_oid,
                position_sz=position_sz,
            )

        return {
            "tp_order_id": tp_oid,
            "sl_order_id": sl_oid,
            "trigger_status": trigger_status,
            "trigger_error": trigger_error,
        }

    def set_tp_sl(
        self,
        pair: str,
        take_profit: Decimal | None = None,
        stop_loss: Decimal | None = None,
        trailing_stop: dict[str, Any] | None = None,
    ) -> dict[str, str | None] | Coroutine[Any, Any, dict[str, str | None]]:
        """Add or replace TP/SL on an existing position (sync or async)."""
        return _sync_or_async(
            self.set_tp_sl_async(
                pair,
                take_profit=take_profit,
                stop_loss=stop_loss,
                trailing_stop=trailing_stop,
            )
        )

    async def update_trailing_stops_async(self) -> list[dict[str, Any]]:
        """Ratchet all tracked trailing stops based on current prices.

        Call periodically (e.g. every 30-60 seconds) to update trailing stop
        loss orders as price moves favorably.
        """
        if not self._trailing_state:
            return []

        updates: list[dict[str, Any]] = []
        for hl_name, state in list(self._trailing_state.items()):
            current_price = await self._fetch_mid_price(hl_name)

            side = state["side"]
            old_best = state["best_price"]

            if side == "long":
                new_best = max(old_best, current_price)
            else:
                new_best = min(old_best, current_price)

            if new_best == old_best:
                continue

            new_sl = self._compute_trailing_sl(
                side, new_best, state["trailing_stop"], state["fixed_sl"],
            )
            old_sl = self._compute_trailing_sl(
                side, old_best, state["trailing_stop"], state["fixed_sl"],
            )

            more_protective = (
                (side == "long" and new_sl > old_sl)
                or (side == "short" and new_sl < old_sl)
            )
            if not more_protective:
                continue

            # Place new SL first, then cancel old — safety ordering.
            # best_price is NOT advanced until placement succeeds, so a
            # failed attempt can be retried on the next poll.
            exchange = self._get_exchange()
            close_is_buy = side == "short"
            rounded_sl = float(self._round_trigger_price(hl_name, new_sl))
            try:
                result = await asyncio.to_thread(
                    exchange.order,
                    hl_name,
                    close_is_buy,
                    state["position_sz"],
                    rounded_sl,
                    {"trigger": {"triggerPx": rounded_sl, "isMarket": True, "tpsl": "sl"}},
                    True,
                )
                if result.get("status") == "ok":
                    statuses = result["response"]["data"]["statuses"]
                    if statuses and isinstance(statuses[0], dict) and "resting" in statuses[0]:
                        new_oid = str(statuses[0]["resting"]["oid"])
                    else:
                        raise HyperscaledError(
                            "Trailing SL replacement returned no resting oid"
                        )
                else:
                    raise HyperscaledError(
                        f"Trailing SL replacement failed: {result.get('status', 'unknown')}"
                    )
            except HyperscaledError as exc:
                state["degraded"] = True
                state["last_error"] = str(exc)
                updates.append({
                    "pair": self._display_pair_from_hl_name(hl_name),
                    "status": "failed",
                    "message": (
                        f"Trailing SL update failed; previous SL left unchanged: {exc}"
                    ),
                })
                continue
            except Exception as exc:
                state["degraded"] = True
                state["last_error"] = str(exc)
                updates.append({
                    "pair": self._display_pair_from_hl_name(hl_name),
                    "status": "failed",
                    "message": (
                        f"Trailing SL update failed; previous SL left unchanged: {exc}"
                    ),
                })
                continue

            # Placement succeeded — now commit the best_price advancement.
            state["best_price"] = new_best

            old_oid = state.get("current_sl_oid")
            if old_oid:
                try:
                    await asyncio.to_thread(exchange.cancel, hl_name, int(old_oid))
                except Exception as exc:
                    state["degraded"] = True
                    state["last_error"] = (
                        f"New trailing SL placed as {new_oid}, but old SL "
                        f"{old_oid} could not be cancelled: {exc}"
                    )
                    state["current_sl_oid"] = new_oid
                    updates.append({
                        "pair": self._display_pair_from_hl_name(hl_name),
                        "status": "partial_failure",
                        "message": state["last_error"],
                    })
                    continue

            state["current_sl_oid"] = new_oid
            state["degraded"] = False
            state["last_error"] = None

            updates.append({
                "pair": self._display_pair_from_hl_name(hl_name),
                "status": "updated",
                "old_sl": str(old_sl),
                "new_sl": str(new_sl),
                "best_price": str(new_best),
            })

        return updates

    def update_trailing_stops(
        self,
    ) -> list[dict[str, Any]] | Coroutine[Any, Any, list[dict[str, Any]]]:
        """Ratchet trailing stops (sync or async)."""
        return _sync_or_async(self.update_trailing_stops_async())

    def _parse_cancel_response(
        self,
        result: dict[str, Any],
        requests: list[dict[str, Any]],
    ) -> list[dict[str, object]]:
        """Translate a Hyperliquid cancel response into structured status dictionaries."""
        if result.get("status") != "ok":
            raise HyperscaledError(
                f"Hyperliquid cancel failed: {result.get('status', 'unknown')}"
            )

        try:
            statuses = result["response"]["data"]["statuses"]
        except (KeyError, TypeError) as exc:
            raise HyperscaledError("Unexpected Hyperliquid cancel response shape") from exc

        if not isinstance(statuses, list) or len(statuses) != len(requests):
            raise HyperscaledError("Unexpected Hyperliquid cancel response shape")

        parsed: list[dict[str, object]] = []
        for request, status_entry in zip(requests, statuses):
            parsed.append(self._parse_cancel_status_entry(request, status_entry))
        return parsed

    def _parse_cancel_status_entry(
        self,
        request: dict[str, Any],
        status_entry: Any,
    ) -> dict[str, object]:
        """Normalize one cancel status entry from the Hyperliquid SDK."""
        message = "Order cancelled."
        status = "cancelled"

        if status_entry == "success":
            pass
        elif isinstance(status_entry, dict) and "error" in status_entry:
            message = str(status_entry["error"])
            status = self._classify_cancel_error(message)
        elif isinstance(status_entry, str):
            message = status_entry
            status = "cancelled" if status_entry.lower() == "success" else self._classify_cancel_error(message)
        else:
            raise HyperscaledError(f"Unexpected Hyperliquid cancel status entry: {status_entry}")

        return {
            "hl_order_id": str(request["oid"]),
            "pair": self._display_pair_from_hl_name(str(request["coin"])),
            "status": status,
            "message": message,
        }

    @staticmethod
    def _classify_cancel_error(message: str) -> str:
        """Map HL cancel errors to stable SDK result statuses."""
        normalized = message.lower()
        if "never placed" in normalized or "unknown" in normalized or "not exist" in normalized:
            return "not_found"
        if (
            "already filled" in normalized
            or "already canceled" in normalized
            or "already cancelled" in normalized
            or "already closed" in normalized
            or "filled" in normalized
            or "canceled" in normalized
            or "cancelled" in normalized
            or "closed" in normalized
        ):
            return "already_closed"
        return "error"

    def _parse_hl_response(
        self,
        result: dict[str, Any],
        pair: str,
        side: str,
        size: Decimal,
        order_type: str,
        scaling_ratio: Decimal,
        take_profit: Decimal | None,
        stop_loss: Decimal | None,
        price: Decimal | None,
    ) -> Order:
        """Translate a Hyperliquid order response into an ``Order`` model."""
        if result.get("status") != "ok":
            raise HyperscaledError(
                f"Hyperliquid order failed: {result.get('status', 'unknown')}"
            )

        try:
            statuses = result["response"]["data"]["statuses"]
            entry = statuses[0]
        except (KeyError, IndexError, TypeError) as exc:
            raise HyperscaledError("Unexpected Hyperliquid response shape") from exc

        if "error" in entry:
            raise HyperscaledError(f"Order rejected by Hyperliquid: {entry['error']}")

        if "filled" in entry:
            fill = entry["filled"]
            oid = str(fill["oid"])
            actual_filled_size = Decimal(str(fill["totalSz"]))
            fill_price = Decimal(str(fill["avgPx"]))
            status = "partial" if actual_filled_size < size else "filled"
            funded_equivalent_size = actual_filled_size * scaling_ratio
        elif "resting" in entry:
            oid = str(entry["resting"]["oid"])
            fill_price = None
            actual_filled_size = None
            status = "pending"
            funded_equivalent_size = size * scaling_ratio
        else:
            raise HyperscaledError(f"Unexpected order status entry: {entry}")

        return Order(
            hl_order_id=oid,
            pair=pair.upper(),
            side=side,  # type: ignore[arg-type]
            size=size,
            filled_size=actual_filled_size,
            funded_equivalent_size=funded_equivalent_size,
            order_type=order_type,  # type: ignore[arg-type]
            status=status,  # type: ignore[arg-type]
            fill_price=fill_price,
            scaling_ratio=scaling_ratio,
            take_profit=take_profit,
            stop_loss=stop_loss,
            created_at=datetime.now(timezone.utc),
        )
