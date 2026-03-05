"""Trading models — orders and positions."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel


class Order(BaseModel):
    """A trade order placed through the Hyperscaled SDK."""

    hl_order_id: str
    pair: str
    side: Literal["long", "short"]
    size: Decimal
    funded_equivalent_size: Decimal
    order_type: Literal["market", "limit"]
    status: Literal["filled", "partial", "pending", "cancelled"]
    fill_price: Decimal | None = None
    scaling_ratio: Decimal
    take_profit: Decimal | None = None
    stop_loss: Decimal | None = None
    created_at: datetime


class Position(BaseModel):
    """An open position on a funded account."""

    symbol: str
    side: Literal["long", "short"]
    size: Decimal
    position_value: Decimal
    entry_price: Decimal
    mark_price: Decimal
    liquidation_price: Decimal | None = None
    unrealized_pnl: Decimal
    take_profit: Decimal | None = None
    stop_loss: Decimal | None = None
    open_time: datetime


class ClosedPosition(Position):
    """A position that has been closed, with realized PnL."""

    realized_pnl: Decimal
    close_time: datetime
