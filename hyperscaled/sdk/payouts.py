"""Payout history SDK interface.

Queries the validator dashboard for payout records and exposes them as
typed ``Payout`` models.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any, TypeVar

import httpx

from hyperscaled.exceptions import HyperscaledError
from hyperscaled.models.payout import Payout
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


def _dt_from_raw(value: Any) -> datetime:
    """Parse a datetime from a raw value (ISO string or epoch ms)."""
    if isinstance(value, str):
        # Try ISO format first
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    # Fall back to epoch milliseconds
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
    except (ValueError, TypeError, OSError):
        return datetime.now(tz=timezone.utc)


def _parse_payout(raw: dict[str, Any]) -> Payout:
    """Convert a raw payout dict from the backend into a Payout model."""
    return Payout(
        date=_dt_from_raw(raw.get("date") or raw.get("timestamp")),
        amount=_decimal(raw.get("amount")),
        token=str(raw.get("token", "USDC")),
        network=str(raw.get("network", "Hyperliquid")),
        tx_hash=raw.get("tx_hash") or raw.get("txHash"),
        status=raw.get("status", "completed"),
    )


class PayoutsClient:
    """Read-only payout history and pending payout queries."""

    def __init__(self, client: HyperscaledClient) -> None:
        self._client = client

    def _resolve_wallet(self) -> str:
        return self._client.resolve_hl_wallet_address()

    async def _fetch_dashboard(self) -> dict[str, Any]:
        """Fetch the validator dashboard payload for the configured wallet."""
        hl_address = self._resolve_wallet()
        path = _HL_DASHBOARD_PATH.format(hl_address=hl_address)

        try:
            response = await self._client.validator_http.get(path)
        except httpx.HTTPError as exc:
            raise HyperscaledError(f"Failed to fetch validator dashboard: {exc}") from exc

        if response.status_code == 404:
            raise HyperscaledError(
                f"No validator dashboard for wallet {hl_address}. "
                "Ensure this address is registered with the validator."
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

    async def history_async(self) -> list[Payout]:
        """Fetch payout history from the validator dashboard.

        Returns an empty list when the backend does not yet expose
        payout data.
        """
        dashboard = await self._fetch_dashboard()
        raw_payouts = dashboard.get("payouts", [])
        if not isinstance(raw_payouts, list):
            return []
        return [_parse_payout(p) for p in raw_payouts if isinstance(p, dict)]

    def history(self) -> list[Payout] | Coroutine[Any, Any, list[Payout]]:
        """Fetch payout history (sync or async)."""
        return _sync_or_async(self.history_async())

    async def pending_async(self) -> Payout | None:
        """Fetch the estimated next payout, if any.

        Looks for payouts with ``status`` of ``"pending"`` or
        ``"processing"`` in the dashboard data.  Returns ``None`` when
        no pending payout exists.
        """
        dashboard = await self._fetch_dashboard()

        # Check for a dedicated pending_payout field first
        pending_raw = dashboard.get("pending_payout")
        if isinstance(pending_raw, dict):
            return _parse_payout(pending_raw)

        # Fall back to scanning the payouts list for non-completed entries
        raw_payouts = dashboard.get("payouts", [])
        if not isinstance(raw_payouts, list):
            return None

        for raw in raw_payouts:
            if isinstance(raw, dict) and raw.get("status") in ("pending", "processing"):
                return _parse_payout(raw)

        return None

    def pending(self) -> Payout | None | Coroutine[Any, Any, Payout | None]:
        """Fetch the pending payout (sync or async)."""
        return _sync_or_async(self.pending_async())
