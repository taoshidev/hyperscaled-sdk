"""Trading models — orders and positions."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel


class Order(BaseModel):
    """A trade order placed or read through the Hyperscaled SDK.

    Supports both the write path (trade submission, where ``hl_order_id`` and
    ``scaling_ratio`` are populated) and the read path (portfolio queries,
    where ``order_id`` and ``limit_price`` are populated instead).
    """

    hl_order_id: str | None = None
    order_id: str | None = None
    pair: str
    side: Literal["long", "short"]
    size: Decimal | None = None
    filled_size: Decimal | None = None
    funded_equivalent_size: Decimal | None = None
    order_type: Literal["market", "limit"]
    status: Literal["filled", "partial", "pending", "cancelled", "open"]
    fill_price: Decimal | None = None
    limit_price: Decimal | None = None
    scaling_ratio: Decimal | None = None
    take_profit: Decimal | None = None
    stop_loss: Decimal | None = None
    trailing_stop: dict | None = None
    tp_order_id: str | None = None
    sl_order_id: str | None = None
    trigger_status: Literal[
        "not_requested", "pending_parent_fill", "placed", "partial_failure", "failed"
    ] = "not_requested"
    trigger_error: str | None = None
    created_at: datetime


class Position(BaseModel):
    """An open position on a funded account."""

    symbol: str
    side: Literal["long", "short"]
    size: Decimal
    position_value: Decimal
    entry_price: Decimal
    mark_price: Decimal | None = None
    liquidation_price: Decimal | None = None
    unrealized_pnl: Decimal
    take_profit: Decimal | None = None
    stop_loss: Decimal | None = None
    open_time: datetime


class ClosedPosition(Position):
    """A position that has been closed, with realized PnL."""

    realized_pnl: Decimal
    close_time: datetime
