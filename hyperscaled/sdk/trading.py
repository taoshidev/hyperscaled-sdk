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
from hyperscaled.sdk.pairs import normalize_pair_to_hl, validate_pair

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

    async def _pre_validate(
        self,
        pair: str,
        side: str,
        size: Decimal,
        order_type: str,
        price: Decimal | None,
    ) -> None:
        """Pre-submission validation hook. No-op until SDK-012."""

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
        validate_pair(pair)

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

        # ── Pre-validation seam (SDK-012) ─────────────────────
        await self._pre_validate(pair, side, size, order_type, price)

        # ── Funded account size ───────────────────────────────
        funded_account_size = self._client.config.account.funded_account_size
        if funded_account_size <= 0:
            raise HyperscaledError(
                "No funded account size configured. "
                "Complete registration first via `client.register.purchase()` "
                "or set account.funded_account_size in config."
            )

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
