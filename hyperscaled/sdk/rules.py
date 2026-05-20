"""Rule engine and validator-backed trade validation."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any, TypeVar

import httpx

from hyperscaled.exceptions import (
    AccountSuspendedError,
    DrawdownBreachError,
    HyperscaledError,
    InsufficientBalanceError,
    UnsupportedPairError,
)
from hyperscaled.models.rules import Rule, TradeValidation
from hyperscaled.sdk.client import _run_sync
from hyperscaled.sdk.pairs import hl_coin_from_entry

if TYPE_CHECKING:
    from hyperscaled.sdk.client import HyperscaledClient

T = TypeVar("T")

_TRADE_PAIRS_PATH = "/trade-pairs"
_HL_DASHBOARD_PATH = "/hl-traders/{hl_address}"
_HL_LIMITS_PATH = "/hl-traders/{hl_address}/limits"
_HL_INFO_URL_DEFAULT = "https://api.hyperliquid.xyz/info"
_RULE_IDS = {
    "pair_unsupported": "SDK012_PAIR_UNSUPPORTED",
    "pair_halted": "SDK012_PAIR_HALTED",
    "pair_allowed": "SDK012_ALLOWED_PAIR",
    "pair_max_leverage": "SDK012_PAIR_MAX_LEVERAGE",
    "account_max_leverage": "SDK012_ACCOUNT_MAX_LEVERAGE",
    "leverage_limit": "SDK012_LEVERAGE_LIMIT",
    "exposure_limit": "SDK012_EXPOSURE_LIMIT",
    "drawdown_breach": "SDK012_DRAWDOWN_BREACH",
    "account_status": "SDK012_ACCOUNT_STATUS",
    "insufficient_balance": "SDK012_INSUFFICIENT_BALANCE",
}


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
    """Coerce *value* to ``Decimal`` and fall back cleanly."""
    if value is None:
        return default
    try:
        return Decimal(str(value))
    except Exception:
        return default


def _candidate_pair_keys(pair: str) -> set[str]:
    """Generate lookup keys for a user-supplied pair string."""
    raw = pair.strip().upper()
    if not raw:
        return set()

    candidates = {raw}
    compact = raw.replace("/", "").replace("-", "")
    if compact:
        candidates.add(compact)

    if raw.endswith("-USDC"):
        base = raw[:-5]
        candidates.update({base, f"{base}USD", f"{base}/USD"})
    elif raw.endswith("-USD"):
        base = raw[:-4]
        candidates.update({base, f"{base}USD", f"{base}/USD", f"{base}-USDC"})
    elif "/" in raw:
        base, quote = raw.split("/", 1)
        candidates.add(base)
        candidates.add(f"{base}{quote}")
        if quote == "USD":
            candidates.add(f"{base}-USDC")
    else:
        candidates.update({f"{raw}USD", f"{raw}/USD", f"{raw}-USDC"})

    return candidates


def _sdk_display_pair(entry: dict[str, Any]) -> str:
    """Convert a validator trade-pair entry to the SDK-facing display value."""
    hl_coin = entry.get("hl_coin")
    pair_id = str(entry.get("trade_pair_id", "")).upper()
    pair = str(entry.get("trade_pair", pair_id)).upper()
    category = str(entry.get("trade_pair_category", "")).lower()

    if category == "crypto":
        # Use hl_coin when present to preserve case-sensitive names like kPEPE
        base = hl_coin if hl_coin else (pair_id[:-3] if pair_id.endswith("USD") else pair.split("/")[0])
        return f"{base}-USDC"

    if "/" in pair:
        return pair.replace("/", "-")

    return pair_id or pair


class RulesClient:
    """Read rules metadata and validate trades against validator state."""

    def __init__(self, client: HyperscaledClient) -> None:
        self._client = client

    async def _fetch_trade_pairs(self) -> list[dict[str, Any]]:
        """Return the validator's currently allowed trade pairs."""
        try:
            response = await self._client.validator_http.get(_TRADE_PAIRS_PATH)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise HyperscaledError.from_http(
                exc, operation="fetching trade pairs"
            ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise HyperscaledError.from_json_decode(
                exc, operation="parsing trade pairs response", body_excerpt=response.text
            ) from exc
        pairs = payload.get("allowed") or payload.get("allowed_trade_pairs")
        if not isinstance(pairs, list):
            raise HyperscaledError(
                "Trade-pairs response missing allowed pairs",
                code="HS_BAD_SHAPE",
                operation="fetching trade pairs",
            )
        return [p for p in pairs if p.get("trade_pair_source") == "hyperliquid"]

    async def _fetch_dashboard(self, hl_address: str) -> dict[str, Any]:
        """Fetch validator dashboard data for the configured HL wallet."""
        path = _HL_DASHBOARD_PATH.format(hl_address=hl_address)
        try:
            response = await self._client.validator_http.get(path)
        except httpx.HTTPError as exc:
            raise HyperscaledError.from_http(
                exc, operation="fetching validator dashboard"
            ) from exc

        if response.status_code == 404:
            raise HyperscaledError(
                f"No validator dashboard for Hyperliquid wallet {hl_address}. "
                "That usually means this address is not registered with the validator yet, "
                "or HYPERSCALED_VALIDATOR_API_URL points at the wrong host. "
                "If you use HYPERSCALED_HL_PRIVATE_KEY only, ensure it matches the wallet "
                "you registered; otherwise set HYPERSCALED_HL_ADDRESS to that registered address.",
                code="HS_DASHBOARD_NOT_FOUND",
                http_status=404,
                operation="fetching validator dashboard",
            )

        try:
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise HyperscaledError.from_http(
                exc, operation="fetching validator dashboard"
            ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise HyperscaledError.from_json_decode(
                exc,
                operation="parsing validator dashboard response",
                body_excerpt=response.text,
            ) from exc
        if (
            not isinstance(payload, dict)
            or payload.get("status") != "success"
            or "dashboard" not in payload
        ):
            raise HyperscaledError(
                "Validator dashboard response has unexpected shape",
                code="HS_BAD_SHAPE",
                operation="fetching validator dashboard",
            )
        return payload["dashboard"]

    async def _fetch_limits(self, hl_address: str) -> dict[str, Any]:
        """Return trader-specific limits from the validator."""
        path = _HL_LIMITS_PATH.format(hl_address=hl_address)
        try:
            response = await self._client.validator_http.get(path)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise HyperscaledError.from_http(
                exc, operation="fetching trader limits"
            ) from exc
        try:
            data: dict[str, Any] = response.json()
        except ValueError as exc:
            raise HyperscaledError.from_json_decode(
                exc, operation="parsing trader limits response", body_excerpt=response.text
            ) from exc
        return data

    async def _fetch_hl_mid_price(self, pair: dict[str, Any]) -> Decimal:
        """Fetch the current Hyperliquid mid price for a pair."""
        coin = hl_coin_from_entry(pair)

        try:
            hl_info_url = self._client.config.hl_info_url
            req: dict[str, Any] = {"type": "allMids"}
            if coin.startswith("xyz:"):
                req["dex"] = "xyz"
            response = await self._client.http.post(hl_info_url, json=req)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise HyperscaledError.from_http(
                exc, operation="fetching Hyperliquid mid price"
            ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise HyperscaledError.from_json_decode(
                exc, operation="parsing Hyperliquid mid price", body_excerpt=response.text
            ) from exc
        if not isinstance(payload, dict) or coin not in payload:
            raise HyperscaledError(
                f"Hyperliquid mid price unavailable for {coin}",
                code="HS_HL_MID_UNAVAILABLE",
                operation="fetching Hyperliquid mid price",
            )
        return _decimal(payload[coin])

    def _resolve_wallet(self) -> str:
        """Return the Hyperliquid wallet address for validator dashboard reads."""
        return self._client.resolve_hl_wallet_address()

    def _find_allowed_pair(self, pair: str, allowed_pairs: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Match a user-supplied pair against the validator's allowed-pair list."""
        candidates = _candidate_pair_keys(pair)
        for entry in allowed_pairs:
            trade_pair_id = str(entry.get("trade_pair_id", "")).upper()
            trade_pair = str(entry.get("trade_pair", "")).upper()
            sdk_pair = _sdk_display_pair(entry).upper()
            if {trade_pair_id, trade_pair, sdk_pair} & candidates:
                return entry
        return None

    def _pair_list_for_message(self, allowed_pairs: list[dict[str, Any]]) -> list[str]:
        """Return a stable list of SDK-facing allowed pairs."""
        return sorted({_sdk_display_pair(entry) for entry in allowed_pairs})

    def _assert_account_status(self, dashboard: dict[str, Any]) -> None:
        """Raise if the validator says the account is not currently tradeable."""
        sub_info = dashboard.get("subaccount_info", {})
        if not isinstance(sub_info, dict):
            sub_info = {}
        status = str(sub_info.get("status", "")).lower()
        if status in {"", "success", "active", "admin"}:
            return

        if status == "eliminated":
            drawdown = dashboard.get("drawdown", {})
            current_drawdown = _decimal(
                drawdown.get("intraday_drawdown_pct") if isinstance(drawdown, dict) else None
            )
            max_drawdown = _decimal(
                drawdown.get("intraday_drawdown_threshold") if isinstance(drawdown, dict) else None
            )
            if current_drawdown > 0 and max_drawdown > 0:
                raise DrawdownBreachError(
                    "Account has breached the drawdown limit and cannot place new trades.",
                    rule_id=_RULE_IDS["drawdown_breach"],
                    limit=str(max_drawdown),
                    actual_value=str(current_drawdown),
                    current_drawdown=current_drawdown,
                    max_drawdown=max_drawdown,
                )

        raise AccountSuspendedError(
            f"Account is not currently tradeable (status: {status}).",
            reason=status,
            suspended_at=datetime.now(timezone.utc),
        )

    def _assert_drawdown(self, dashboard: dict[str, Any]) -> None:
        """Raise when drawdown shows the account has already breached.

        intraday_drawdown_pct is in percentage points (0.132 = 0.132%).
        intraday_drawdown_threshold is a decimal fraction (0.05 = 5%).
        Normalise both to percentage points before comparing.
        """
        drawdown = dashboard.get("drawdown", {})
        if not isinstance(drawdown, dict):
            return

        current_pct = abs(_decimal(drawdown.get("intraday_drawdown_pct")))  # e.g. 0.132
        limit_pct = _decimal(drawdown.get("intraday_drawdown_threshold")) * 100  # e.g. 0.05 → 5.0

        if limit_pct > 0 and current_pct >= limit_pct:
            raise DrawdownBreachError(
                f"Account has breached the intraday drawdown limit "
                f"({float(current_pct):.3f}% of {float(limit_pct):.1f}% limit).",
                rule_id=_RULE_IDS["drawdown_breach"],
                limit=str(limit_pct),
                actual_value=str(current_pct),
                current_drawdown=current_pct,
                max_drawdown=limit_pct,
            )

        # Also check EOD trailing drawdown
        eod_pct = abs(_decimal(drawdown.get("eod_drawdown_pct")))
        eod_limit_pct = _decimal(drawdown.get("eod_drawdown_threshold")) * 100

        if eod_limit_pct > 0 and eod_pct >= eod_limit_pct:
            raise DrawdownBreachError(
                f"Account has breached the trailing drawdown limit "
                f"({float(eod_pct):.3f}% of {float(eod_limit_pct):.1f}% limit).",
                rule_id=_RULE_IDS["drawdown_breach"],
                limit=str(eod_limit_pct),
                actual_value=str(eod_pct),
                current_drawdown=eod_pct,
                max_drawdown=eod_limit_pct,
            )

    @staticmethod
    def _account_context(dashboard: dict[str, Any]) -> tuple[Decimal, Decimal, Decimal, bool]:
        """Extract funded balance, current exposure, HWM, and challenge mode."""
        sub_info = dashboard.get("subaccount_info", {})
        positions = dashboard.get("positions", {})
        challenge_period = dashboard.get("challenge_period", {})

        if not isinstance(sub_info, dict):
            sub_info = {}
        if not isinstance(positions, dict):
            positions = {}
        if not isinstance(challenge_period, dict):
            challenge_period = {}

        account_size = _decimal(sub_info.get("account_size"))
        funded_balance = account_size
        total_leverage = _decimal(positions.get("total_leverage"))
        current_exposure = account_size * total_leverage
        in_challenge = challenge_period.get("bucket") == "SUBACCOUNT_CHALLENGE"
        return (
            funded_balance,
            current_exposure,
            account_size,
            bool(in_challenge),
        )

    async def supported_pairs_async(self) -> list[str]:
        """Return the list of currently supported trading pairs from the validator."""
        allowed_pairs = await self._fetch_trade_pairs()
        return self._pair_list_for_message(allowed_pairs)

    def supported_pairs(self) -> list[str] | Coroutine[Any, Any, list[str]]:
        """Return supported pairs synchronously or asynchronously."""
        return _sync_or_async(self.supported_pairs_async())

    async def list_all_async(self) -> list[Rule]:
        """Return a structured summary of currently allowed pair and leverage rules."""
        allowed_pairs = await self._fetch_trade_pairs()
        rules: list[Rule] = []

        for entry in allowed_pairs:
            sdk_pair = _sdk_display_pair(entry)
            pair_id = str(entry.get("trade_pair_id", sdk_pair))
            max_leverage = str(entry.get("max_leverage", "unknown"))
            category = str(entry.get("trade_pair_category", "unknown"))

            rules.append(
                Rule(
                    rule_id=f"{_RULE_IDS['pair_allowed']}::{pair_id}",
                    category="pairs",
                    description=f"{sdk_pair} is allowed for trading.",
                    current_value=None,
                    limit="allowed",
                    applies_to=category,
                )
            )
            rules.append(
                Rule(
                    rule_id=f"{_RULE_IDS['pair_max_leverage']}::{pair_id}",
                    category="leverage",
                    description=f"Maximum leverage for {sdk_pair}.",
                    current_value=None,
                    limit=max_leverage,
                    applies_to=sdk_pair,
                )
            )


        return rules

    def list_all(self) -> list[Rule] | Coroutine[Any, Any, list[Rule]]:
        """Return the current validator rule set synchronously or asynchronously."""
        return _sync_or_async(self.list_all_async())

    async def validate_trade_async(
        self,
        pair: str,
        side: str,
        size: Decimal,
        order_type: str,
        price: Decimal | None = None,
    ) -> TradeValidation:
        """Validate a proposed trade against validator-backed pair and account rules."""
        allowed_pairs = await self._fetch_trade_pairs()
        pair_entry = self._find_allowed_pair(pair, allowed_pairs)
        if pair_entry is None:
            supported_pairs = self._pair_list_for_message(allowed_pairs)
            normalized_pair = pair.strip().upper() or pair
            raise UnsupportedPairError(
                f"Unsupported pair {pair!r}. Supported pairs: {', '.join(supported_pairs)}",
                rule_id=_RULE_IDS["pair_unsupported"],
                limit="allowed_trade_pairs",
                actual_value=normalized_pair,
                pair=normalized_pair,
                supported_pairs=supported_pairs,
            )

        wallet = self._resolve_wallet()
        dashboard, balance_status = await asyncio.gather(
            self._fetch_dashboard(wallet),
            self._client.account.check_balance_async(wallet),
        )
        self._assert_account_status(dashboard)
        self._assert_drawdown(dashboard)

        _funded_balance, _current_funded_exposure, _account_size, _in_challenge = self._account_context(dashboard)
        if _funded_balance <= 0:
            raise HyperscaledError("Validator dashboard reported a non-positive funded balance.")

        hl_balance = balance_status.balance
        if hl_balance <= 0:
            raise HyperscaledError("Hyperliquid balance is zero — deposit funds before trading.")
        if not balance_status.meets_minimum:
            raise InsufficientBalanceError(
                f"HL balance ${float(hl_balance):,.2f} is below the "
                f"${float(balance_status.minimum_required):,.2f} minimum required to trade.",
                rule_id=_RULE_IDS["insufficient_balance"],
                limit=str(balance_status.minimum_required),
                actual_value=str(hl_balance),
                balance=hl_balance,
                minimum_required=balance_status.minimum_required,
            )

        return TradeValidation(valid=True, violations=[])

    def validate_trade(
        self,
        pair: str,
        side: str,
        size: Decimal,
        order_type: str,
        price: Decimal | None = None,
    ) -> TradeValidation | Coroutine[Any, Any, TradeValidation]:
        """Validate a trade synchronously or asynchronously."""
        return _sync_or_async(self.validate_trade_async(pair, side, size, order_type, price))
