"""Tests for the exception hierarchy (SDK-004)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from hyperscaled.exceptions import (
    AccountSuspendedError,
    DrawdownBreachError,
    ExposureLimitError,
    HyperscaledError,
    InsufficientBalanceError,
    LeverageLimitError,
    OrderFrequencyError,
    RuleViolationError,
    TemporarilyHaltedPairError,
    UnsupportedPairError,
)

_RULE_KWARGS = {"rule_id": "TEST_001", "limit": "10", "actual_value": "15"}


class TestHyperscaledError:
    def test_message(self) -> None:
        err = HyperscaledError("something broke")
        assert err.message == "something broke"
        assert str(err) == "something broke"

    def test_is_exception(self) -> None:
        assert issubclass(HyperscaledError, Exception)


class TestRuleViolationError:
    def test_inherits_hyperscaled_error(self) -> None:
        err = RuleViolationError("violation", **_RULE_KWARGS)
        assert isinstance(err, HyperscaledError)

    def test_fields(self) -> None:
        err = RuleViolationError("violation", rule_id="R1", limit="10", actual_value="15")
        assert err.rule_id == "R1"
        assert err.limit == "10"
        assert err.actual_value == "15"
        assert err.message == "violation"


class TestUnsupportedPairError:
    def test_inherits_rule_violation(self) -> None:
        err = UnsupportedPairError(
            "LINK-USDC not supported",
            **_RULE_KWARGS,
            pair="LINK-USDC",
            supported_pairs=["BTC-USDC", "ETH-USDC"],
        )
        assert isinstance(err, RuleViolationError)
        assert isinstance(err, HyperscaledError)

    def test_fields(self) -> None:
        err = UnsupportedPairError(
            "bad pair",
            **_RULE_KWARGS,
            pair="LINK-USDC",
            supported_pairs=["BTC-USDC"],
        )
        assert err.pair == "LINK-USDC"
        assert err.supported_pairs == ["BTC-USDC"]


class TestTemporarilyHaltedPairError:
    def test_inherits_rule_violation(self) -> None:
        err = TemporarilyHaltedPairError(
            "BTC-USDC halted",
            **_RULE_KWARGS,
            pair="BTC-USDC",
        )
        assert isinstance(err, RuleViolationError)
        assert isinstance(err, HyperscaledError)

    def test_fields(self) -> None:
        err = TemporarilyHaltedPairError(
            "halted",
            **_RULE_KWARGS,
            pair="BTC-USDC",
        )
        assert err.pair == "BTC-USDC"


class TestLeverageLimitError:
    def test_inherits_rule_violation(self) -> None:
        err = LeverageLimitError(
            "too much leverage",
            **_RULE_KWARGS,
            requested_leverage=50.0,
            max_leverage=20.0,
        )
        assert isinstance(err, RuleViolationError)

    def test_fields(self) -> None:
        err = LeverageLimitError(
            "too much leverage",
            **_RULE_KWARGS,
            requested_leverage=50.0,
            max_leverage=20.0,
        )
        assert err.requested_leverage == 50.0
        assert err.max_leverage == 20.0


class TestInsufficientBalanceError:
    def test_inherits_rule_violation(self) -> None:
        err = InsufficientBalanceError(
            "balance too low",
            **_RULE_KWARGS,
            balance=Decimal("500"),
            minimum_required=Decimal("1000"),
        )
        assert isinstance(err, RuleViolationError)

    def test_fields(self) -> None:
        err = InsufficientBalanceError(
            "balance too low",
            **_RULE_KWARGS,
            balance=Decimal("500"),
            minimum_required=Decimal("1000"),
        )
        assert err.balance == Decimal("500")
        assert err.minimum_required == Decimal("1000")


class TestExposureLimitError:
    def test_inherits_rule_violation(self) -> None:
        err = ExposureLimitError(
            "exposure exceeded",
            **_RULE_KWARGS,
            current_exposure=Decimal("150000"),
            max_exposure=Decimal("125000"),
        )
        assert isinstance(err, RuleViolationError)

    def test_fields(self) -> None:
        err = ExposureLimitError(
            "exposure exceeded",
            **_RULE_KWARGS,
            current_exposure=Decimal("150000"),
            max_exposure=Decimal("125000"),
        )
        assert err.current_exposure == Decimal("150000")
        assert err.max_exposure == Decimal("125000")


class TestDrawdownBreachError:
    def test_inherits_rule_violation(self) -> None:
        err = DrawdownBreachError(
            "drawdown breached",
            **_RULE_KWARGS,
            current_drawdown=Decimal("-11"),
            max_drawdown=Decimal("-10"),
        )
        assert isinstance(err, RuleViolationError)

    def test_fields(self) -> None:
        err = DrawdownBreachError(
            "drawdown breached",
            **_RULE_KWARGS,
            current_drawdown=Decimal("-11"),
            max_drawdown=Decimal("-10"),
        )
        assert err.current_drawdown == Decimal("-11")
        assert err.max_drawdown == Decimal("-10")


class TestOrderFrequencyError:
    def test_inherits_rule_violation(self) -> None:
        err = OrderFrequencyError(
            "too many orders",
            **_RULE_KWARGS,
            requests_per_minute=120,
            limit_per_minute=60,
        )
        assert isinstance(err, RuleViolationError)

    def test_fields(self) -> None:
        err = OrderFrequencyError(
            "too many orders",
            **_RULE_KWARGS,
            requests_per_minute=120,
            limit_per_minute=60,
        )
        assert err.requests_per_minute == 120
        assert err.limit_per_minute == 60


class TestAccountSuspendedError:
    def test_inherits_hyperscaled_error_not_rule_violation(self) -> None:
        err = AccountSuspendedError(
            "account suspended",
            reason="drawdown breach",
            suspended_at=datetime(2026, 3, 5, tzinfo=timezone.utc),
        )
        assert isinstance(err, HyperscaledError)
        assert not isinstance(err, RuleViolationError)

    def test_fields(self) -> None:
        ts = datetime(2026, 3, 5, 12, 0, 0, tzinfo=timezone.utc)
        err = AccountSuspendedError(
            "account suspended",
            reason="drawdown breach",
            suspended_at=ts,
        )
        assert err.reason == "drawdown breach"
        assert err.suspended_at == ts
        assert err.message == "account suspended"
