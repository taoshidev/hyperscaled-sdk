"""Entity miner discovery client."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import TYPE_CHECKING, Any, TypeVar

import httpx

from hyperscaled.exceptions import HyperscaledError
from hyperscaled.models import EntityMiner, PricingTier, ProfitSplit
from hyperscaled.sdk.client import _run_sync

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
    result: T = _run_sync(coro)
    return result


def _normalize_payout_cadence(value: Any, cadence_days: Any) -> str:
    """Normalize backend cadence values to a stable SDK string."""
    if isinstance(value, str) and value.strip():
        return value.strip().lower()

    if isinstance(cadence_days, int):
        known = {7: "weekly", 14: "biweekly", 30: "monthly"}
        return known.get(cadence_days, f"every_{cadence_days}_days")

    return "unknown"


def _profit_split_from_raw(raw: Any) -> ProfitSplit:
    """Convert multiple backend representations to ProfitSplit."""
    if isinstance(raw, dict):
        trader = int(raw["trader_pct"])
        miner = int(raw["miner_pct"])
        return ProfitSplit(trader_pct=trader, miner_pct=miner)

    trader_pct = int(raw)
    return ProfitSplit(trader_pct=trader_pct, miner_pct=100 - trader_pct)


def _pricing_tier_from_raw(raw: dict[str, Any]) -> PricingTier:
    """Convert a backend tier payload into the SDK model."""
    account_size = raw.get("account_size", raw.get("accountSize"))
    cost = raw.get("cost", raw.get("price_usdc", raw.get("priceUsdc")))
    profit_split_raw = raw.get("profit_split", raw.get("profitSplit"))

    if account_size is None or cost is None or profit_split_raw is None:
        raise HyperscaledError("Miner tier payload is missing required fields.")

    return PricingTier(
        account_size=int(account_size),
        cost=cost,
        profit_split=_profit_split_from_raw(profit_split_raw),
    )


def _entity_miner_from_raw(raw: dict[str, Any]) -> EntityMiner:
    """Convert a backend miner payload into the SDK model."""
    tiers_raw = raw.get("pricing_tiers", raw.get("tiers", []))
    pricing_tiers = [_pricing_tier_from_raw(tier) for tier in tiers_raw]

    available_sizes = raw.get("available_account_sizes")
    if available_sizes is None:
        available_sizes = [tier.account_size for tier in pricing_tiers]

    return EntityMiner(
        name=raw["name"],
        slug=raw["slug"],
        pricing_tiers=pricing_tiers,
        payout_cadence=_normalize_payout_cadence(
            raw.get("payout_cadence"),
            raw.get("payout_cadence_days", raw.get("payoutCadenceDays")),
        ),
        available_account_sizes=[int(size) for size in available_sizes],
        brand_color=raw.get("brand_color", raw.get("color")),
    )


class MinersClient:
    """Read-only access to the Hyperscaled miner catalog."""

    def __init__(self, client: HyperscaledClient) -> None:
        self._client = client

    async def list_all_async(self) -> list[EntityMiner]:
        """Fetch all entity miners from the Hyperscaled API."""
        try:
            response = await self._client.http.get("/api/v1/miners")
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HyperscaledError(
                f"Failed to fetch miners: {exc.response.status_code} {exc.response.reason_phrase}"
            ) from exc
        except httpx.HTTPError as exc:
            raise HyperscaledError(f"Failed to fetch miners: {exc}") from exc

        payload = response.json()
        if not isinstance(payload, list):
            raise HyperscaledError("Miner list response must be a JSON array.")

        return [_entity_miner_from_raw(item) for item in payload]

    def list_all(self) -> list[EntityMiner] | Coroutine[Any, Any, list[EntityMiner]]:
        """Fetch all miners synchronously or asynchronously."""
        return _sync_or_async(self.list_all_async())

    async def get_async(self, slug: str) -> EntityMiner:
        """Fetch a single entity miner by slug."""
        try:
            response = await self._client.http.get(f"/api/v1/miners/{slug}")
        except httpx.HTTPError as exc:
            raise HyperscaledError(f"Failed to fetch miner '{slug}': {exc}") from exc

        if response.status_code == 404:
            raise HyperscaledError(f"Miner '{slug}' not found.")

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HyperscaledError(
                f"Failed to fetch miner '{slug}': "
                f"{exc.response.status_code} {exc.response.reason_phrase}"
            ) from exc

        payload = response.json()
        if not isinstance(payload, dict):
            raise HyperscaledError("Miner detail response must be a JSON object.")

        return _entity_miner_from_raw(payload)

    def get(self, slug: str) -> EntityMiner | Coroutine[Any, Any, EntityMiner]:
        """Fetch one miner synchronously or asynchronously."""
        return _sync_or_async(self.get_async(slug))

    async def compare_async(self, slugs: list[str] | None = None) -> list[EntityMiner]:
        """Fetch multiple miners for side-by-side comparison."""
        if slugs is None:
            return await self.list_all_async()
        return [await self.get_async(slug) for slug in slugs]

    def compare(
        self, slugs: list[str] | None = None
    ) -> list[EntityMiner] | Coroutine[Any, Any, list[EntityMiner]]:
        """Compare miners synchronously or asynchronously."""
        return _sync_or_async(self.compare_async(slugs))
