"""Account models — info, leverage limits, status."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel


class LeverageLimits(BaseModel):
    """Leverage constraints at the account and per-pair level."""

    account_level: float
    position_level: dict[str, float]


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
