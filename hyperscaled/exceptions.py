"""Exception hierarchy for Hyperscaled SDK."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any


class HyperscaledError(Exception):
    """Base exception for all Hyperscaled errors."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class RuleViolationError(HyperscaledError):
    """A Vanta Network rule was violated."""

    def __init__(
        self,
        message: str,
        *,
        rule_id: str,
        limit: str,
        actual_value: str,
        code: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        self.rule_id = rule_id
        self.limit = limit
        self.actual_value = actual_value
        self.code = code or rule_id
        self.context = context or {}
        super().__init__(message)

    @property
    def current_value(self) -> str:
        """Compatibility alias for newer rule payload naming."""
        return self.actual_value

    @property
    def allowed_value(self) -> str:
        """Compatibility alias for newer rule payload naming."""
        return self.limit


class UnsupportedPairError(RuleViolationError):
    """Trade attempted on a pair not supported by the entity miner."""

    def __init__(
        self,
        message: str,
        *,
        rule_id: str,
        limit: str,
        actual_value: str,
        pair: str,
        supported_pairs: list[str],
    ) -> None:
        self.pair = pair
        self.supported_pairs = supported_pairs
        super().__init__(message, rule_id=rule_id, limit=limit, actual_value=actual_value)


class TemporarilyHaltedPairError(RuleViolationError):
    """Trade pair exists but is not currently allowed for trading."""

    def __init__(
        self,
        message: str,
        *,
        rule_id: str,
        limit: str,
        actual_value: str,
        pair: str,
    ) -> None:
        self.pair = pair
        super().__init__(message, rule_id=rule_id, limit=limit, actual_value=actual_value)


class LeverageLimitError(RuleViolationError):
    """Requested leverage exceeds the allowed limit."""

    def __init__(
        self,
        message: str,
        *,
        rule_id: str,
        limit: str,
        actual_value: str,
        requested_leverage: float,
        max_leverage: float,
    ) -> None:
        self.requested_leverage = requested_leverage
        self.max_leverage = max_leverage
        super().__init__(message, rule_id=rule_id, limit=limit, actual_value=actual_value)


class InsufficientBalanceError(RuleViolationError):
    """Account balance is below the required minimum ($1,000)."""

    def __init__(
        self,
        message: str,
        *,
        rule_id: str,
        limit: str,
        actual_value: str,
        balance: Decimal,
        minimum_required: Decimal,
    ) -> None:
        self.balance = balance
        self.minimum_required = minimum_required
        super().__init__(message, rule_id=rule_id, limit=limit, actual_value=actual_value)


class ExposureLimitError(RuleViolationError):
    """Funded account notional exposure would be exceeded."""

    def __init__(
        self,
        message: str,
        *,
        rule_id: str,
        limit: str,
        actual_value: str,
        current_exposure: Decimal,
        max_exposure: Decimal,
    ) -> None:
        self.current_exposure = current_exposure
        self.max_exposure = max_exposure
        super().__init__(message, rule_id=rule_id, limit=limit, actual_value=actual_value)


class DrawdownBreachError(RuleViolationError):
    """Account drawdown exceeds the maximum allowed limit."""

    def __init__(
        self,
        message: str,
        *,
        rule_id: str,
        limit: str,
        actual_value: str,
        current_drawdown: Decimal,
        max_drawdown: Decimal,
    ) -> None:
        self.current_drawdown = current_drawdown
        self.max_drawdown = max_drawdown
        super().__init__(message, rule_id=rule_id, limit=limit, actual_value=actual_value)


class OrderFrequencyError(RuleViolationError):
    """Order submission rate exceeds the allowed limit."""

    def __init__(
        self,
        message: str,
        *,
        rule_id: str,
        limit: str,
        actual_value: str,
        requests_per_minute: int,
        limit_per_minute: int,
    ) -> None:
        self.requests_per_minute = requests_per_minute
        self.limit_per_minute = limit_per_minute
        super().__init__(message, rule_id=rule_id, limit=limit, actual_value=actual_value)


class AccountSuspendedError(HyperscaledError):
    """The funded account has been suspended."""

    def __init__(
        self,
        message: str,
        *,
        reason: str,
        suspended_at: datetime,
    ) -> None:
        self.reason = reason
        self.suspended_at = suspended_at
        super().__init__(message)


class PaymentError(HyperscaledError):
    """x402 signing/settlement failure or missing dependencies."""

    def __init__(self, message: str, *, tx_hash: str | None = None) -> None:
        self.tx_hash = tx_hash
        super().__init__(message)


class RegistrationError(HyperscaledError):
    """Backend returned an error during registration."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(message)


class UnsupportedAccountSizeError(HyperscaledError):
    """Requested account size is not available from this miner."""

    def __init__(
        self,
        message: str,
        *,
        requested_size: int,
        available_sizes: list[int],
    ) -> None:
        self.requested_size = requested_size
        self.available_sizes = available_sizes
        super().__init__(message)


class InvalidMinerError(HyperscaledError):
    """Miner slug not found in the catalog."""

    def __init__(self, message: str, *, slug: str) -> None:
        self.slug = slug
        super().__init__(message)


class RegistrationPollTimeoutError(RegistrationError):
    """Registration polling exceeded the configured timeout."""

    def __init__(
        self,
        message: str,
        *,
        hl_address: str,
        last_status: str,
        elapsed_seconds: float,
    ) -> None:
        self.hl_address = hl_address
        self.last_status = last_status
        self.elapsed_seconds = elapsed_seconds
        super().__init__(message)
