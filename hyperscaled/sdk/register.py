"""Funded account registration client.

Handles the end-to-end purchase flow: wallet validation, balance check,
tier resolution, x402 USDC payment, and backend registration submission.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Coroutine
from decimal import Decimal
from typing import TYPE_CHECKING, Any, TypeVar

import httpx

from hyperscaled.exceptions import (
    HyperscaledError,
    InvalidMinerError,
    PaymentError,
    RegistrationError,
    UnsupportedAccountSizeError,
)
from hyperscaled.models.account import MINIMUM_BALANCE
from hyperscaled.models.registration import RegistrationStatus
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


class RegisterClient:
    """Purchase funded trading accounts via x402 USDC payment."""

    def __init__(self, client: HyperscaledClient) -> None:
        self._client = client

    # ── Helpers ───────────────────────────────────────────────

    async def _resolve_tier_index(self, miner_slug: str, account_size: int) -> tuple[int, Decimal]:
        """Find the tier index and cost for the given account size.

        Returns ``(tier_index, cost)`` or raises
        :class:`InvalidMinerError` / :class:`UnsupportedAccountSizeError`.
        """
        try:
            miner = await self._client.miners.get_async(miner_slug)
        except HyperscaledError as exc:
            if "not found" in exc.message.lower():
                raise InvalidMinerError(
                    f"Miner '{miner_slug}' not found.",
                    slug=miner_slug,
                ) from exc
            raise

        for idx, tier in enumerate(miner.pricing_tiers):
            if tier.account_size == account_size:
                return idx, tier.cost

        available = [t.account_size for t in miner.pricing_tiers]
        raise UnsupportedAccountSizeError(
            f"Account size ${account_size:,} is not available from '{miner_slug}'. "
            f"Available sizes: {', '.join(f'${s:,}' for s in available)}",
            requested_size=account_size,
            available_sizes=available,
        )

    def _resolve_private_key(self, private_key: str | None) -> str:
        """Return the Base private key from param or environment."""
        resolved = private_key or os.environ.get("HYPERSCALED_BASE_PRIVATE_KEY", "")
        if not resolved:
            raise PaymentError(
                "No Base private key provided. "
                "Pass private_key= or set HYPERSCALED_BASE_PRIVATE_KEY."
            )
        return resolved

    def _sign_payment(self, payment_requirements: dict[str, Any], private_key: str) -> str:
        """Sign the x402 payment payload using the x402 library.

        Lazy-imports the x402 package so it remains an optional dependency.
        """
        try:
            from x402.client import x402Client  # type: ignore[import-not-found]
            from x402.crypto.evm import EthAccountSigner  # type: ignore[import-not-found]
        except ImportError as exc:
            raise PaymentError(
                "x402 package not installed. Install with: pip install 'x402[httpx,evm]>=2.0'"
            ) from exc

        try:
            signer = EthAccountSigner(private_key)
            x402_client = x402Client(signer)
            return x402_client.create_payment_header(payment_requirements)  # type: ignore[no-any-return]
        except Exception as exc:
            raise PaymentError(f"x402 payment signing failed: {exc}") from exc

    # ── Main purchase flow ────────────────────────────────────

    async def purchase_async(
        self,
        miner_slug: str,
        account_size: int,
        hl_wallet: str,
        payout_wallet: str | None = None,
        *,
        email: str,
        private_key: str | None = None,
    ) -> RegistrationStatus:
        """Execute the full registration purchase flow.

        1. Validate wallets
        2. Check HL balance (must be >= $1,000)
        3. Resolve pricing tier
        4. POST to /api/register (expect 402)
        5. Sign x402 payment
        6. POST again with payment-signature header
        7. Return RegistrationStatus
        """
        # 1. Validate wallets
        if not self._client.account.validate_wallet(hl_wallet):
            raise ValueError(
                f"Invalid HL wallet address: {hl_wallet!r} "
                "-- expected format 0x followed by 40 hex chars"
            )

        if not email.strip():
            raise ValueError("Email is required for registration.")

        if payout_wallet and not self._client.account.validate_wallet(payout_wallet):
            raise ValueError(
                f"Invalid payout wallet address: {payout_wallet!r} "
                "-- expected format 0x followed by 40 hex chars"
            )

        # 2. Check HL balance
        from hyperscaled.exceptions import InsufficientBalanceError

        balance_status = await self._client.account.check_balance_async(hl_wallet)
        if not balance_status.meets_minimum:
            raise InsufficientBalanceError(
                f"HL wallet balance ${balance_status.balance:,.2f} is below the "
                f"${MINIMUM_BALANCE:,.2f} minimum required for registration.",
                rule_id="registration_min_balance",
                limit=str(MINIMUM_BALANCE),
                actual_value=str(balance_status.balance),
                balance=balance_status.balance,
                minimum_required=MINIMUM_BALANCE,
            )

        # 3. Resolve tier
        tier_index, _cost = await self._resolve_tier_index(miner_slug, account_size)

        # 4. Resolve private key
        resolved_key = self._resolve_private_key(private_key)

        # 5. Initial POST — expect 402
        body = {
            "minerSlug": miner_slug,
            "hlAddress": hl_wallet,
            "accountSize": account_size,
            "email": email,
            "tierIndex": tier_index,
        }
        if payout_wallet:
            body["payoutAddress"] = payout_wallet

        try:
            initial_resp = await self._client.http.post("/api/register", json=body)
        except httpx.HTTPError as exc:
            raise RegistrationError(f"Registration request failed: {exc}") from exc

        if initial_resp.status_code != 402:
            raise RegistrationError(
                f"Expected 402 Payment Required, got {initial_resp.status_code}: "
                f"{initial_resp.text}",
                status_code=initial_resp.status_code,
            )

        payment_requirements = initial_resp.json()

        # 6. Sign x402 payment
        payment_signature = self._sign_payment(payment_requirements, resolved_key)

        # 7. Paid POST
        try:
            paid_resp = await self._client.http.post(
                "/api/register",
                json=body,
                headers={"payment-signature": payment_signature},
            )
        except httpx.HTTPError as exc:
            raise RegistrationError(f"Paid registration request failed: {exc}") from exc

        if paid_resp.status_code != 200:
            raise RegistrationError(
                f"Registration failed: {paid_resp.status_code} {paid_resp.text}",
                status_code=paid_resp.status_code,
            )

        data = paid_resp.json()
        return RegistrationStatus(
            status=data.get("status", "pending"),
            account_size=account_size,
            tx_hash=data.get("txHash"),
            message=data.get("message"),
        )

    def purchase(
        self,
        miner_slug: str,
        account_size: int,
        hl_wallet: str,
        payout_wallet: str | None = None,
        *,
        email: str,
        private_key: str | None = None,
    ) -> RegistrationStatus | Coroutine[Any, Any, RegistrationStatus]:
        """Purchase a funded account (sync or async)."""
        return _sync_or_async(
            self.purchase_async(
                miner_slug,
                account_size,
                hl_wallet,
                payout_wallet,
                email=email,
                private_key=private_key,
            )
        )
