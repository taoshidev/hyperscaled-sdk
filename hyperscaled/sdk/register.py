"""Funded account registration client.

Handles the end-to-end purchase flow: wallet validation, balance check,
tier resolution, x402 USDC payment, and backend registration submission.
Also provides registration status polling against the Hyperscaled API
(``config.api.hyperscaled_base_url``): ``GET /api/registration-status?hl_address=...``.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Callable, Coroutine
from decimal import Decimal
from typing import TYPE_CHECKING, Any, TypeVar

import httpx

from hyperscaled.exceptions import (
    HyperscaledError,
    InvalidMinerError,
    PaymentError,
    RegistrationError,
    RegistrationPollTimeoutError,
    UnsupportedAccountSizeError,
)
from hyperscaled.models.account import MINIMUM_BALANCE
from hyperscaled.models.registration import TERMINAL_STATUSES, RegistrationStatus
from hyperscaled.sdk.base_usdc import fetch_base_usdc_balance
from hyperscaled.sdk.client import _run_sync

if TYPE_CHECKING:
    from hyperscaled.sdk.client import HyperscaledClient

T = TypeVar("T")

_DEFAULT_POLL_INTERVAL = 5.0
_DEFAULT_POLL_TIMEOUT = 300.0


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

    def _persist_funded_account_id(self, funded_account_id: str | None) -> None:
        """Persist a funded account ID when the backend provides one."""
        if not funded_account_id:
            return
        self._client.config.set_value("account.funded_account_id", funded_account_id)
        self._client.config.save()

    def _persist_funded_account_size(self, account_size: int) -> None:
        """Persist funded account size to local config."""
        if account_size <= 0:
            return
        self._client.config.set_value("account.funded_account_size", str(account_size))
        self._client.config.save()

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

    def payment_wallet_address(self, private_key: str | None = None) -> str:
        """EVM address that pays registration.

        Resolved from ``HYPERSCALED_BASE_PRIVATE_KEY`` or *private_key*.
        """
        try:
            from eth_account import Account  # type: ignore[import-not-found]
        except ImportError as exc:
            raise PaymentError(
                "eth_account not available. Install with: pip install 'x402[evm]>=2.0'"
            ) from exc

        key = self._resolve_private_key(private_key)
        normalized = key if key.startswith("0x") else "0x" + key
        return Account.from_key(normalized).address

    async def payment_wallet_usdc_balance_async(self, private_key: str | None = None) -> Decimal:
        """USDC balance on Base for the payment wallet."""
        addr = self.payment_wallet_address(private_key)
        return await fetch_base_usdc_balance(
            addr,
            testnet=self._client.config.api.testnet,
        )

    def payment_wallet_usdc_balance(
        self, private_key: str | None = None
    ) -> Decimal | Coroutine[Any, Any, Decimal]:
        """USDC balance on Base (sync or async)."""
        return _sync_or_async(self.payment_wallet_usdc_balance_async(private_key))

    def _sign_payment(self, initial_resp: Any, private_key: str) -> dict[str, str]:
        """Sign the x402 payment payload using the x402 library.

        Lazy-imports the x402 package so it remains an optional dependency.
        Returns a dict of headers to include in the payment retry request.
        """
        try:
            from eth_account import Account  # type: ignore[import-not-found]
            from x402.client import x402ClientSync  # type: ignore[import-not-found]
            from x402.http.constants import (
                PAYMENT_REQUIRED_HEADER,  # type: ignore[import-not-found]
            )
            from x402.http.utils import (
                decode_payment_required_header,  # type: ignore[import-not-found]
            )
            from x402.http.x402_http_client import (
                x402HTTPClientSync,  # type: ignore[import-not-found]
            )
            from x402.mechanisms.evm.exact import (
                register_exact_evm_client,  # type: ignore[import-not-found]
            )
        except ImportError as exc:
            raise PaymentError(
                "x402 package not installed. Install with: pip install 'x402[evm]>=2.0'"
            ) from exc

        try:
            key = private_key if private_key.startswith("0x") else "0x" + private_key
            account = Account.from_key(key)

            client = x402ClientSync()
            register_exact_evm_client(client, account)
            http_client = x402HTTPClientSync(client)

            payment_required_header = initial_resp.headers.get(PAYMENT_REQUIRED_HEADER)
            if payment_required_header:
                payment_required = decode_payment_required_header(payment_required_header)
            else:
                data = initial_resp.json()
                version = data.get("x402Version", 1)
                if version == 2:
                    from x402.schemas import PaymentRequired  # type: ignore[import-not-found]

                    payment_required = PaymentRequired.model_validate(data)
                else:
                    from x402.schemas.v1 import PaymentRequiredV1  # type: ignore[import-not-found]

                    payment_required = PaymentRequiredV1.model_validate(data)

            payload = client.create_payment_payload(payment_required)
            return http_client.encode_payment_signature_header(payload)
        except PaymentError:
            raise
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

        # 2. Check HL balance (skip on testnet)
        if not self._client.config.api.testnet:
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
        body: dict[str, Any] = {
            "minerSlug": miner_slug,
            "hlAddress": hl_wallet,
            "accountSize": account_size,
            "email": email,
            "tierIndex": tier_index,
        }
        if payout_wallet:
            body["payoutAddress"] = payout_wallet
        if self._client.config.api.testnet:
            body["network"] = "base-sepolia"

        try:
            initial_resp = await self._client.validator_http.post("/api/register", json=body)
        except httpx.HTTPError as exc:
            raise RegistrationError(f"Registration request failed: {exc}") from exc

        if initial_resp.status_code != 402:
            raise RegistrationError(
                f"Expected 402 Payment Required, got {initial_resp.status_code}: "
                f"{initial_resp.text}",
                status_code=initial_resp.status_code,
            )

        # 6. Sign x402 payment
        payment_headers = self._sign_payment(initial_resp, resolved_key)

        # 7. Paid POST
        try:
            paid_resp = await self._client.validator_http.post(
                "/api/register",
                json=body,
                headers=payment_headers,
            )
        except httpx.HTTPError as exc:
            raise RegistrationError(f"Paid registration request failed: {exc}") from exc

        if paid_resp.status_code != 200:
            raise RegistrationError(
                f"Registration failed: {paid_resp.status_code} {paid_resp.text}",
                status_code=paid_resp.status_code,
            )

        data = paid_resp.json()
        self._persist_funded_account_size(account_size)
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

    # ── Status polling ─────────────────────────────────────────

    async def check_status_async(self, hl_address: str) -> RegistrationStatus:
        """Fetch the current registration status for an HL wallet.

        Uses ``self._client.http`` (base URL ``config.api.hyperscaled_base_url``):
        ``GET /api/registration-status?hl_address=<address>``.

        Returns a :class:`RegistrationStatus`.
        """
        if not self._client.account.validate_wallet(hl_address):
            raise ValueError(
                f"Invalid HL wallet address: {hl_address!r} "
                "-- expected format 0x followed by 40 hex chars"
            )

        try:
            resp = await self._client.http.get(
                "/api/registration-status",
                params={"hl_address": hl_address},
            )
        except httpx.HTTPError as exc:
            raise RegistrationError(f"Registration status request failed: {exc}") from exc

        if resp.status_code == 400:
            data = resp.json()
            raise RegistrationError(
                data.get("error", "Invalid request"),
                status_code=400,
            )

        if resp.status_code != 200:
            raise RegistrationError(
                f"Registration status check failed: {resp.status_code} {resp.text}",
                status_code=resp.status_code,
            )

        data = resp.json()
        result = RegistrationStatus(
            status=data.get("status", "pending"),
            hl_address=data.get("hl_address", hl_address),
            registration_id=data.get("registration_id"),
            funded_account_id=data.get("funded_account_id"),
            account_size=data.get("account_size"),
            estimated_time=data.get("estimated_time"),
            tx_hash=data.get("tx_hash") or data.get("txHash"),
            message=data.get("message"),
        )
        if result.is_success:
            self._persist_funded_account_id(result.funded_account_id)
            if data.get("account_size"):
                self._persist_funded_account_size(int(data["account_size"]))
        return result

    def check_status(
        self, hl_address: str
    ) -> RegistrationStatus | Coroutine[Any, Any, RegistrationStatus]:
        """Check registration status (sync or async)."""
        return _sync_or_async(self.check_status_async(hl_address))

    async def poll_until_complete_async(
        self,
        hl_address: str,
        *,
        interval_seconds: float = _DEFAULT_POLL_INTERVAL,
        timeout_seconds: float = _DEFAULT_POLL_TIMEOUT,
        on_status: Callable[[RegistrationStatus], None] | None = None,
    ) -> RegistrationStatus:
        """Poll registration status until a terminal state is reached.

        Calls :meth:`check_status_async` repeatedly, sleeping
        ``interval_seconds`` between attempts.  Raises
        :class:`RegistrationPollTimeoutError` if ``timeout_seconds`` elapses
        without reaching a terminal status.

        The optional ``on_status`` callback is invoked with each intermediate
        :class:`RegistrationStatus` so callers can display progress.
        """
        start = time.monotonic()

        last_status: RegistrationStatus | None = None
        while True:
            elapsed = time.monotonic() - start
            if elapsed >= timeout_seconds:
                raise RegistrationPollTimeoutError(
                    f"Registration polling timed out after {elapsed:.0f}s. "
                    f"Last status: {last_status.status if last_status else 'unknown'}",
                    hl_address=hl_address,
                    last_status=last_status.status if last_status else "unknown",
                    elapsed_seconds=elapsed,
                )

            result = await self.check_status_async(hl_address)
            last_status = result

            if on_status is not None:
                on_status(result)

            if result.status in TERMINAL_STATUSES:
                return result

            remaining = timeout_seconds - (time.monotonic() - start)
            if remaining <= 0:
                raise RegistrationPollTimeoutError(
                    f"Registration polling timed out after {timeout_seconds:.0f}s. "
                    f"Last status: {last_status.status if last_status else 'unknown'}",
                    hl_address=hl_address,
                    last_status=last_status.status if last_status else "unknown",
                    elapsed_seconds=timeout_seconds,
                )

            await asyncio.sleep(min(interval_seconds, remaining))

    def poll_until_complete(
        self,
        hl_address: str,
        *,
        interval_seconds: float = _DEFAULT_POLL_INTERVAL,
        timeout_seconds: float = _DEFAULT_POLL_TIMEOUT,
        on_status: Callable[[RegistrationStatus], None] | None = None,
    ) -> RegistrationStatus | Coroutine[Any, Any, RegistrationStatus]:
        """Poll registration status (sync or async)."""
        return _sync_or_async(
            self.poll_until_complete_async(
                hl_address,
                interval_seconds=interval_seconds,
                timeout_seconds=timeout_seconds,
                on_status=on_status,
            )
        )
