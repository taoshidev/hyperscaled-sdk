"""Entity miner models."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel


class PricingTier(BaseModel):
    """A funded-account pricing option offered by an entity miner."""

    account_size: int
    cost: Decimal
    profit_split: ProfitSplit


class ProfitSplit(BaseModel):
    """Profit-sharing ratio between trader and entity miner."""

    trader_pct: int
    miner_pct: int


class EntityMiner(BaseModel):
    """An entity miner on the Hyperscaled platform."""

    name: str
    slug: str
    pricing_tiers: list[PricingTier]
    payout_cadence: str
    available_account_sizes: list[int]
    brand_color: str | None = None
