"""Account models — info, leverage limits, status, balance."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

MINIMUM_BALANCE = Decimal("1000.00")


class LeverageLimits(BaseModel):
    """Leverage constraints at the account and per-pair level."""

    account_level: float
    position_level: dict[str, float]
    max_position_per_pair_usd: float = 0.0
    max_portfolio_usd: float = 0.0


class BalanceStatus(BaseModel):
    """Result of a Hyperliquid wallet balance check."""

    balance: Decimal
    meets_minimum: bool
    minimum_required: Decimal = MINIMUM_BALANCE


class AccountInfo(BaseModel):
    """Full status and configuration for a funded account."""

    status: Literal["active", "suspended", "pending_kyc", "breached"]
    account_type: Literal["challenge", "funded"] = "funded"
    funded_account_size: int
    hl_wallet_address: str
    payout_wallet_address: str
    entity_miner: str
    # Intraday drawdown (resets each day)
    current_drawdown: Decimal
    max_drawdown_limit: Decimal
    # End-of-day trailing drawdown
    eod_drawdown: Decimal = Decimal("0")
    eod_drawdown_limit: Decimal = Decimal("0")
    # Payout period performance
    total_realized_pnl: Decimal = Decimal("0")
    current_equity_ratio: Decimal = Decimal("1")  # e.g. 1.05 = +5%
    # Portfolio leverage
    current_leverage: Decimal = Decimal("0")   # leverage currently in use
    max_portfolio_leverage: Decimal = Decimal("0")  # max allowed given account type
    leverage_limits: LeverageLimits
    hl_balance: Decimal
    funded_balance: Decimal
    kyc_status: Literal["not_started", "pending", "verified"]
