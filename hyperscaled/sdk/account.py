"""Account management SDK interface.

Provides Hyperliquid wallet setup, balance checking, and continuous
balance monitoring.  Balance checks query the Hyperliquid info API
directly (no Hyperscaled backend round-trip).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from decimal import Decimal
from typing import TYPE_CHECKING, Any, TypeVar

import httpx

from hyperscaled.exceptions import HyperscaledError
from hyperscaled.models.account import MINIMUM_BALANCE, BalanceStatus
from hyperscaled.sdk.config import is_valid_hl_address

if TYPE_CHECKING:
    from hyperscaled.sdk.client import HyperscaledClient

T = TypeVar("T")

_HL_INFO_URL = "https://api.hyperliquid.xyz/info"
_BALANCE_POLL_INTERVAL = 5.0


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


class AccountClient:
    """Account-related helpers for Hyperliquid wallet setup and balance flows."""

    def __init__(self, client: HyperscaledClient) -> None:
        self._client = client

    # ── Wallet validation (SDK-006) ──────────────────────────

    def validate_wallet(self, address: str) -> bool:
        """Return ``True`` when ``address`` is a valid Hyperliquid wallet format."""
        return is_valid_hl_address(address)

    # ── Account setup (SDK-007) ──────────────────────────────

    async def setup_async(self, wallet_address: str) -> None:
        """Validate *wallet_address* and persist it to local config.

        Raises :class:`ValueError` when the address format is invalid.
        """
        if not self.validate_wallet(wallet_address):
            raise ValueError(
                f"Invalid wallet address: {wallet_address!r} "
                "— expected format 0x followed by 40 hex chars"
            )
        self._client.config.set_value("wallet.hl_address", wallet_address)
        self._client.config.save()

    def setup(self, wallet_address: str) -> None | Coroutine[Any, Any, None]:
        """Validate and save the HL wallet (sync or async)."""
        return _sync_or_async(self.setup_async(wallet_address))

    # ── Balance check (SDK-007) ──────────────────────────────

    async def _fetch_hl_balance(self, wallet_address: str) -> Decimal:
        """Query the Hyperliquid info API for the wallet's USDC equity."""
        payload = {"type": "clearinghouseState", "user": wallet_address}
        try:
            response = await self._client.http.post(_HL_INFO_URL, json=payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HyperscaledError(
                f"Hyperliquid balance request failed: "
                f"{exc.response.status_code} {exc.response.reason_phrase}"
            ) from exc
        except httpx.HTTPError as exc:
            raise HyperscaledError(f"Hyperliquid balance request failed: {exc}") from exc

        data = response.json()
        try:
            equity = data["marginSummary"]["accountValue"]
        except (KeyError, TypeError) as exc:
            raise HyperscaledError("Unexpected Hyperliquid balance response shape") from exc
        return Decimal(str(equity))

    def _resolve_wallet(self, wallet_address: str | None = None) -> str:
        """Return the wallet to use: explicit override or configured."""
        resolved = wallet_address or self._client.config.wallet.hl_address
        if not resolved:
            raise HyperscaledError(
                "No Hyperliquid wallet configured. "
                "Run `client.account.setup(wallet)` or `hyperscaled account setup <wallet>` first."
            )
        return resolved

    async def check_balance_async(self, wallet_address: str | None = None) -> BalanceStatus:
        """Return current balance and whether the wallet meets the minimum.

        Uses the configured HL wallet unless *wallet_address* is explicitly
        provided.
        """
        resolved = self._resolve_wallet(wallet_address)
        balance = await self._fetch_hl_balance(resolved)
        return BalanceStatus(
            balance=balance,
            meets_minimum=balance >= MINIMUM_BALANCE,
        )

    def check_balance(
        self, wallet_address: str | None = None
    ) -> BalanceStatus | Coroutine[Any, Any, BalanceStatus]:
        """Check balance (sync or async)."""
        return _sync_or_async(self.check_balance_async(wallet_address))

    # ── Balance watcher (SDK-007) ─────────────────────────────

    async def watch_balance(
        self,
        callback: Callable[[BalanceStatus], Any | Awaitable[Any]],
        *,
        wallet_address: str | None = None,
        poll_interval: float = _BALANCE_POLL_INTERVAL,
    ) -> None:
        """Continuously poll balance and invoke *callback* on each update.

        Runs until the task is cancelled via ``asyncio.CancelledError``.
        """
        resolved = self._resolve_wallet(wallet_address)
        while True:
            status = await self.check_balance_async(resolved)
            result = callback(status)
            if asyncio.iscoroutine(result) or asyncio.isfuture(result):
                await result
            await asyncio.sleep(poll_interval)
