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
from hyperscaled.models.account import MINIMUM_BALANCE, AccountInfo, BalanceStatus, LeverageLimits
from hyperscaled.sdk.config import is_valid_hl_address

if TYPE_CHECKING:
    from hyperscaled.sdk.client import HyperscaledClient

T = TypeVar("T")

_HL_INFO_URL_DEFAULT = "https://api.hyperliquid.xyz/info"
_BALANCE_POLL_INTERVAL = 5.0
_HL_DASHBOARD_PATH = "/hl-traders/{hl_address}"
_TRADE_PAIRS_PATH = "/trade-pairs"
_PORTFOLIO_LEVERAGE_CAP: dict[str, float] = {
    "crypto": 5.0,
    "forex": 20.0,
    "indices": 10.0,
    "equities": 2.0,
}


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
        """Return total portfolio value per the Vanta translation spec:

            portfolio_value = perp.marginSummary.accountValue
                            + (spot.USDC.total - spot.USDC.hold)

        perp.marginSummary.accountValue already includes locked margin and
        unrealized PnL. spot.USDC.hold is the portion of spot USDC locked as
        perp collateral — subtracting it avoids double-counting with the perp
        value. Together they represent the full economic value of the account.
        """
        hl_info_url = self._client.config.hl_info_url
        perp_value, spot_free = await asyncio.gather(
            self._fetch_perps_equity(hl_info_url, wallet_address),
            self._fetch_spot_usdc_free(hl_info_url, wallet_address),
        )
        return perp_value + spot_free

    async def _fetch_perps_equity(self, hl_info_url: str, wallet_address: str) -> Decimal:
        """Return the perps clearinghouse account value."""
        payload = {"type": "clearinghouseState", "user": wallet_address}
        try:
            response = await self._client.http.post(hl_info_url, json=payload)
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

    async def _fetch_spot_usdc(self, hl_info_url: str, wallet_address: str) -> Decimal:
        """Return the raw spot USDC total (including held/locked amount)."""
        payload = {"type": "spotClearinghouseState", "user": wallet_address}
        try:
            response = await self._client.http.post(hl_info_url, json=payload)
            response.raise_for_status()
        except httpx.HTTPError:
            return Decimal("0")

        data = response.json()
        for balance in data.get("balances", []):
            if balance.get("coin") == "USDC":
                return Decimal(str(balance.get("total", "0")))
        return Decimal("0")

    async def _fetch_spot_usdc_free(self, hl_info_url: str, wallet_address: str) -> Decimal:
        """Return the free spot USDC: total minus the amount held as perp collateral.

        spot.USDC.hold is the portion locked as margin for open positions.
        It already appears in perp.marginSummary.accountValue, so subtracting
        it here prevents double-counting in the portfolio value calculation.
        """
        payload = {"type": "spotClearinghouseState", "user": wallet_address}
        try:
            response = await self._client.http.post(hl_info_url, json=payload)
            response.raise_for_status()
        except httpx.HTTPError:
            return Decimal("0")

        data = response.json()
        for balance in data.get("balances", []):
            if balance.get("coin") == "USDC":
                total = Decimal(str(balance.get("total", "0")))
                hold = Decimal(str(balance.get("hold", "0")))
                return max(Decimal("0"), total - hold)
        return Decimal("0")

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

    async def check_spot_balance_async(self, wallet_address: str | None = None) -> Decimal:
        """Return the free spot USDC (total minus amount held as perp collateral)."""
        resolved = self._resolve_wallet(wallet_address)
        return await self._fetch_spot_usdc_free(self._client.config.hl_info_url, resolved)

    def check_spot_balance(
        self, wallet_address: str | None = None
    ) -> Decimal | Coroutine[Any, Any, Decimal]:
        """Check spot USDC balance (sync or async)."""
        return _sync_or_async(self.check_spot_balance_async(wallet_address))

    # ── Account info ───────────────────────────────────────────

    def _resolve_wallet_for_validator(self) -> str:
        """Return the HL wallet address for validator dashboard lookups."""
        return self._client.resolve_hl_wallet_address()

    async def _fetch_dashboard(self, hl_address: str) -> dict[str, Any]:
        """Fetch validator dashboard data for the given HL wallet."""
        path = _HL_DASHBOARD_PATH.format(hl_address=hl_address)
        try:
            response = await self._client.validator_http.get(path)
        except httpx.HTTPError as exc:
            raise HyperscaledError(f"Failed to fetch validator dashboard: {exc}") from exc

        if response.status_code == 404:
            raise HyperscaledError(
                f"No validator dashboard for Hyperliquid wallet {hl_address}. "
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

    @staticmethod
    def _map_status(dashboard: dict[str, Any]) -> str:
        """Map the validator dashboard status to an AccountInfo status string."""
        raw = str(dashboard.get("status", "")).lower()
        if raw in {"", "success", "active", "admin"}:
            return "active"
        if raw == "eliminated":
            return "breached"
        if raw in {"suspended", "paused"}:
            return "suspended"
        # Treat anything else as suspended
        return "suspended"

    @staticmethod
    def _map_kyc_status(dashboard: dict[str, Any]) -> str:
        """Map dashboard KYC fields to the AccountInfo kyc_status literal."""
        kyc = dashboard.get("kyc_status", dashboard.get("kyc", ""))
        raw = str(kyc).lower()
        if raw in {"verified", "approved"}:
            return "verified"
        if raw in {"pending", "in_progress", "submitted"}:
            return "pending"
        return "not_started"

    async def info_async(self) -> AccountInfo:
        """Fetch complete account info from the validator dashboard."""
        hl_address = self._resolve_wallet_for_validator()
        dashboard = await self._fetch_dashboard(hl_address)

        # Fetch HL balance
        balance_status = await self.check_balance_async(hl_address)

        # The validator response nests account data under subaccount_info
        sub_info = dashboard.get("subaccount_info", {})
        if not isinstance(sub_info, dict):
            sub_info = {}

        drawdown = dashboard.get("drawdown", {})
        if not isinstance(drawdown, dict):
            drawdown = {}

        challenge_period = dashboard.get("challenge_period", {})
        if not isinstance(challenge_period, dict):
            challenge_period = {}
        bucket = str(challenge_period.get("bucket", "")).upper()
        account_type = "challenge" if "CHALLENGE" in bucket else "funded"

        account_size = sub_info.get("account_size", 0) or 0

        current_drawdown = Decimal(str(drawdown.get("intraday_drawdown_pct", "0") or "0"))
        max_drawdown = Decimal(str(drawdown.get("intraday_drawdown_threshold", "0") or "0"))
        eod_drawdown = Decimal(str(drawdown.get("eod_drawdown_pct", "0") or "0"))
        eod_drawdown_limit = Decimal(str(drawdown.get("eod_drawdown_threshold", "0") or "0"))
        current_equity_ratio = Decimal(str(drawdown.get("current_equity", "1") or "1"))

        account_size_data = dashboard.get("account_size_data", {})
        if not isinstance(account_size_data, dict):
            account_size_data = {}
        total_realized_pnl = Decimal(str(account_size_data.get("total_realized_pnl", "0") or "0"))

        # Current portfolio leverage from positions
        positions_section = dashboard.get("positions", {})
        current_leverage = Decimal(str(
            positions_section.get("total_leverage", "0")
            if isinstance(positions_section, dict) else "0"
        ))

        # Max portfolio leverage — crypto cap, halved in challenge mode
        _CRYPTO_CAP = Decimal("5")
        _CHALLENGE_DIVISOR = Decimal("4")
        base_cap = _CRYPTO_CAP  # default; refined by asset_class if needed
        asset_class = str(sub_info.get("asset_class", "crypto")).lower()
        _CAPS = {"crypto": Decimal("5"), "forex": Decimal("20"), "indices": Decimal("10"), "equities": Decimal("2")}
        base_cap = _CAPS.get(asset_class, _CRYPTO_CAP)
        max_portfolio_leverage = base_cap / _CHALLENGE_DIVISOR if account_type == "challenge" else base_cap

        # Build per-pair leverage from trade pairs
        leverage_limits = await self.limits_async()

        return AccountInfo(
            status=self._map_status(sub_info),  # type: ignore[arg-type]
            account_type=account_type,  # type: ignore[arg-type]
            funded_account_size=int(account_size),
            hl_wallet_address=hl_address,
            payout_wallet_address=sub_info.get("payout_address") or self._client.config.wallet.payout_address or "",
            entity_miner=str(sub_info.get("asset_class", "")),
            current_drawdown=current_drawdown,
            max_drawdown_limit=max_drawdown,
            eod_drawdown=eod_drawdown,
            eod_drawdown_limit=eod_drawdown_limit,
            total_realized_pnl=total_realized_pnl,
            current_equity_ratio=current_equity_ratio,
            current_leverage=current_leverage,
            max_portfolio_leverage=max_portfolio_leverage,
            leverage_limits=leverage_limits,
            hl_balance=balance_status.balance,
            funded_balance=Decimal(str(account_size)),
            kyc_status=self._map_kyc_status(dashboard),  # type: ignore[arg-type]
        )

    def info(self) -> AccountInfo | Coroutine[Any, Any, AccountInfo]:
        """Fetch account info (sync or async)."""
        return _sync_or_async(self.info_async())

    async def _fetch_trade_pairs(self) -> list[dict[str, Any]]:
        """Return the validator's currently allowed trade pairs."""
        try:
            response = await self._client.validator_http.get(_TRADE_PAIRS_PATH)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HyperscaledError(
                f"Failed to fetch trade pairs: "
                f"{exc.response.status_code} {exc.response.reason_phrase}"
            ) from exc
        except httpx.HTTPError as exc:
            raise HyperscaledError(f"Failed to fetch trade pairs: {exc}") from exc

        payload = response.json()
        pairs = payload.get("allowed_trade_pairs")
        if not isinstance(pairs, list):
            raise HyperscaledError("Trade-pairs response missing allowed_trade_pairs")
        return pairs

    async def limits_async(self) -> LeverageLimits:
        """Fetch leverage limits from the validator."""
        trade_pairs = await self._fetch_trade_pairs()

        position_level: dict[str, float] = {}
        for entry in trade_pairs:
            pair_id = str(entry.get("trade_pair_id", "")).upper()
            trade_pair = str(entry.get("trade_pair", pair_id)).upper()
            category = str(entry.get("trade_pair_category", "")).lower()

            # Build display name consistent with rules.py _sdk_display_pair
            if category == "crypto":
                base = pair_id[:-3] if pair_id.endswith("USD") else trade_pair.split("/")[0]
                display = f"{base}-USDC"
            elif "/" in trade_pair:
                display = trade_pair.replace("/", "-")
            else:
                display = pair_id or trade_pair

            max_leverage = float(entry.get("max_leverage", 1))
            position_level[display] = max_leverage

        # Account-level cap is the max across all category caps
        account_level = max(_PORTFOLIO_LEVERAGE_CAP.values()) if _PORTFOLIO_LEVERAGE_CAP else 1.0

        return LeverageLimits(
            account_level=account_level,
            position_level=position_level,
        )

    def limits(self) -> LeverageLimits | Coroutine[Any, Any, LeverageLimits]:
        """Fetch leverage limits (sync or async)."""
        return _sync_or_async(self.limits_async())

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
