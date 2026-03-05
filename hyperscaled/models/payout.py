"""Payout models."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel


class Payout(BaseModel):
    """A payout record from a funded account."""

    date: datetime
    amount: Decimal
    token: str
    network: str
    tx_hash: str | None = None
    status: Literal["completed", "pending", "processing", "failed"]
