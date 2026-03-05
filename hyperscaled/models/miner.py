"""Entity miner models."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel


class PricingTier(BaseModel):
    """A funded-account pricing option offered by an entity miner."""

    account_size: int
    cost: Decimal


class ProfitSplit(BaseModel):
    """Profit-sharing ratio between trader and entity miner."""

    trader_pct: int
    miner_pct: int


class EntityMiner(BaseModel):
    """An entity miner on the Hyperscaled platform."""

    name: str
    slug: str
    url: str | None = None
    pricing_tiers: list[PricingTier]
    profit_split: ProfitSplit
    payout_cadence: str
    supported_pairs: list[str]
    leverage_limits: dict[str, float]
    available_account_sizes: list[int]
