"""KYC verification SDK interface.

Queries the Hyperscaled frontend API for SumSub KYC status and token
generation, exposing results as typed models.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import TYPE_CHECKING, Any, TypeVar

import httpx

from hyperscaled.exceptions import HyperscaledError
from hyperscaled.models.kyc import KycInfo, KycTokenResponse
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


class KYCClient:
    """SumSub KYC status and verification token queries."""

    def __init__(self, client: HyperscaledClient) -> None:
        self._client = client

    def _resolve_wallet(self) -> str:
        return self._client.resolve_hl_wallet_address()

    async def status_async(self) -> KycInfo:
        """Fetch KYC verification status for the configured wallet."""
        wallet = self._resolve_wallet()

        try:
            response = await self._client.http.get("/api/kyc/status", params={"wallet": wallet})
        except httpx.HTTPError as exc:
            raise HyperscaledError(f"Failed to fetch KYC status: {exc}") from exc

        if response.status_code in (400, 404):
            raise HyperscaledError(
                "KYC request failed. Check your wallet address and registration status."
            )

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HyperscaledError(
                f"Failed to fetch KYC status: "
                f"{exc.response.status_code} {exc.response.reason_phrase}"
            ) from exc

        data = response.json()
        return KycInfo(
            wallet=data["wallet"],
            kyc_status=data["kycStatus"],
            verified=data["verified"],
            verified_at=data.get("verifiedAt"),
        )

    def status(self) -> KycInfo | Coroutine[Any, Any, KycInfo]:
        """Fetch KYC status (sync or async)."""
        return _sync_or_async(self.status_async())

    async def is_verified_async(self) -> bool:
        """Return whether the configured wallet has passed KYC."""
        info = await self.status_async()
        return info.verified

    def is_verified(self) -> bool | Coroutine[Any, Any, bool]:
        """Check KYC verification (sync or async)."""
        return _sync_or_async(self.is_verified_async())

    async def start_async(self) -> KycTokenResponse:
        """Create a SumSub applicant and return an SDK access token."""
        wallet = self._resolve_wallet()

        try:
            response = await self._client.http.post("/api/kyc/token", json={"wallet": wallet})
        except httpx.HTTPError as exc:
            raise HyperscaledError(f"Failed to start KYC: {exc}") from exc

        if response.status_code in (400, 404):
            raise HyperscaledError(
                "KYC request failed. Check your wallet address and registration status."
            )

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HyperscaledError(
                f"Failed to start KYC: {exc.response.status_code} {exc.response.reason_phrase}"
            ) from exc

        data = response.json()
        return KycTokenResponse(
            token=data["token"],
            kyc_status=data["kycStatus"],
        )

    def start(self) -> KycTokenResponse | Coroutine[Any, Any, KycTokenResponse]:
        """Start KYC verification (sync or async)."""
        return _sync_or_async(self.start_async())
