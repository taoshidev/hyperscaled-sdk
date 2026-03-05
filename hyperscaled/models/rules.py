"""Rule models — network rules, violations, and trade validation."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class Rule(BaseModel):
    """A Vanta Network rule that governs funded-account behavior."""

    rule_id: str
    category: Literal["leverage", "pairs", "drawdown", "exposure", "order_frequency", "payout"]
    description: str
    current_value: str | None = None
    limit: str
    applies_to: str | None = None


class RuleViolation(BaseModel):
    """A specific violation of a Vanta Network rule."""

    rule: Rule
    actual_value: str
    message: str


class TradeValidation(BaseModel):
    """Result of validating a trade against all applicable rules."""

    valid: bool
    violations: list[RuleViolation]
