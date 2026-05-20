"""Exception hierarchy for Hyperscaled SDK."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import httpx


class HyperscaledError(Exception):
    """Base exception for all Hyperscaled errors.

    Carries structured context so callers (and the REST wrapping layer) can
    react programmatically without parsing the message string. Use the
    :meth:`from_http` and :meth:`from_json_decode` classmethods when wrapping
    upstream errors — they pick the right subclass and populate fields
    consistently.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        http_status: int | None = None,
        operation: str | None = None,
        body_excerpt: str | None = None,
        retryable: bool = False,
    ) -> None:
        self.message = message
        self.code = code
        self.http_status = http_status
        self.operation = operation
        self.body_excerpt = body_excerpt
        self.retryable = retryable
        super().__init__(message)

    @classmethod
    def from_http(
        cls,
        exc: httpx.HTTPError,
        *,
        operation: str,
    ) -> HyperscaledError:
        """Wrap an :mod:`httpx` error with structured context.

        Routes to :class:`HyperscaledServerError` for 5xx/network/timeout
        (retryable) and :class:`HyperscaledClientError` for 4xx (not retryable).
        The original exception is preserved as the cause via ``raise … from exc``
        at the call site.
        """
        import httpx as _httpx

        if isinstance(exc, _httpx.TimeoutException):
            return HyperscaledServerError(
                f"Timed out while {operation}.",
                code="HS_NETWORK_TIMEOUT",
                operation=operation,
                retryable=True,
            )
        if isinstance(exc, _httpx.HTTPStatusError):
            status = exc.response.status_code
            body = exc.response.text or ""
            if status >= 500:
                return HyperscaledServerError(
                    f"Hyperscaled API returned {status} while {operation}.",
                    code=f"HS_API_{status}",
                    http_status=status,
                    operation=operation,
                    body_excerpt=body,
                    retryable=True,
                )
            return HyperscaledClientError(
                f"Hyperscaled API returned {status} while {operation}.",
                code=f"HS_API_{status}",
                http_status=status,
                operation=operation,
                body_excerpt=body,
                retryable=False,
            )
        return HyperscaledServerError(
            f"Network error while {operation}: {type(exc).__name__}.",
            code="HS_NETWORK_ERROR",
            operation=operation,
            retryable=True,
        )

    @classmethod
    def from_json_decode(
        cls,
        exc: json.JSONDecodeError,  # noqa: ARG003 — accepted for API symmetry
        *,
        operation: str,
        body_excerpt: str,
    ) -> HyperscaledError:
        """Wrap a JSON decode error with the response body excerpt for debugging."""
        return HyperscaledServerError(
            f"Hyperscaled API returned malformed JSON while {operation}.",
            code="HS_BAD_JSON",
            operation=operation,
            body_excerpt=body_excerpt if body_excerpt else None,
            retryable=False,
        )


class HyperscaledClientError(HyperscaledError):
    """4xx-class error — the caller likely needs to fix something."""


class HyperscaledServerError(HyperscaledError):
    """5xx-class, timeout, or network error — likely transient, retry sensible."""


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
