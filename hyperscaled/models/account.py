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


class BalanceStatus(BaseModel):
    """Result of a Hyperliquid wallet balance check."""

    balance: Decimal
    meets_minimum: bool
    minimum_required: Decimal = MINIMUM_BALANCE


class AccountInfo(BaseModel):
    """Full status and configuration for a funded account."""

    status: Literal["active", "suspended", "pending_kyc", "breached"]
    funded_account_size: int
    hl_wallet_address: str
    payout_wallet_address: str
    entity_miner: str
    current_drawdown: Decimal
    max_drawdown_limit: Decimal
    leverage_limits: LeverageLimits
    hl_balance: Decimal
    funded_balance: Decimal
    kyc_status: Literal["not_started", "pending", "verified"]
