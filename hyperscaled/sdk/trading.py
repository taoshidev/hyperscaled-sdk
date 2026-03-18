"""Trade submission SDK interface.

Submits orders to Hyperliquid via ``hyperliquid-python-sdk`` and translates
the results into funded-account equivalents using the scaling ratio.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any, TypeVar

from hyperscaled.exceptions import HyperscaledError
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
            self._exchange = Exchange(wallet=wallet)
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
            self._info = Info(skip_ws=True)
        return self._info

    def _resolve_wallet(self) -> str:
        """Return the configured HL wallet required for order lookups."""
        resolved = self._client.config.wallet.hl_address
        if not resolved:
            raise HyperscaledError(
                "No Hyperliquid wallet configured. "
                "Run `client.account.setup(wallet)` or `hyperscaled account setup <wallet>` first."
            )
        return resolved

    @staticmethod
    def _display_pair_from_hl_name(name: str) -> str:
        """Map Hyperliquid asset names back to the SDK pair format when possible."""
        pair = f"{name.upper()}-USDC"
        return pair if pair in SUPPORTED_PAIRS else name.upper()

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
    ) -> Order:
        """Submit an order and return translated funded-account execution info."""
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

        # ── Pre-validation seam (SDK-012) ─────────────────────
        await self._pre_validate(pair, side, size, order_type, price)

        # ── Live HL balance ───────────────────────────────────
        balance_status = await self._client.account.check_balance_async()
        hl_balance = balance_status.balance
        if hl_balance <= 0:
            raise HyperscaledError("Hyperliquid account balance is zero or negative")

        # ── Scaling ratio ─────────────────────────────────────
        scaling_ratio = Decimal(str(funded_account_size)) / hl_balance

        # ── Normalize pair ────────────────────────────────────
        hl_name = normalize_pair_to_hl(pair)
        is_buy = side == "long"

        # ── Place order via HL SDK ────────────────────────────
        exchange = self._get_exchange()
        try:
            if order_type == "market":
                result = await asyncio.to_thread(
                    exchange.market_open, hl_name, is_buy, float(size)
                )
            else:
                result = await asyncio.to_thread(
                    exchange.order,
                    hl_name, is_buy, float(size), float(price),  # type: ignore[arg-type]
                    {"limit": {"tif": "Gtc"}},
                )
        except Exception as exc:
            raise HyperscaledError(f"Hyperliquid order submission failed: {exc}") from exc

        # ── Parse response ────────────────────────────────────
        return self._parse_hl_response(
            result, pair, side, size, order_type, scaling_ratio,
            take_profit, stop_loss, price,
        )

    def submit(
        self,
        pair: str,
        side: str,
        size: Decimal,
        order_type: str,
        price: Decimal | None = None,
        take_profit: Decimal | None = None,
        stop_loss: Decimal | None = None,
    ) -> Order | Coroutine[Any, Any, Order]:
        """Submit an order (sync or async), following the pattern from AccountClient."""
        return _sync_or_async(
            self.submit_async(pair, side, size, order_type, price, take_profit, stop_loss)
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
            filled_size = Decimal(str(fill["totalSz"]))
            fill_price = Decimal(str(fill["avgPx"]))
            status = "partial" if filled_size < size else "filled"
            funded_equivalent_size = filled_size * scaling_ratio
        elif "resting" in entry:
            oid = str(entry["resting"]["oid"])
            fill_price = None
            filled_size = None
            status = "pending"
            funded_equivalent_size = size * scaling_ratio
        else:
            raise HyperscaledError(f"Unexpected order status entry: {entry}")

        return Order(
            hl_order_id=oid,
            pair=pair.upper(),
            side=side,  # type: ignore[arg-type]
            size=size,
            funded_equivalent_size=funded_equivalent_size,
            order_type=order_type,  # type: ignore[arg-type]
            status=status,  # type: ignore[arg-type]
            fill_price=fill_price,
            scaling_ratio=scaling_ratio,
            take_profit=take_profit,
            stop_loss=stop_loss,
            created_at=datetime.now(timezone.utc),
        )
