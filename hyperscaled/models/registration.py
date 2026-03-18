"""Registration models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class RegistrationStatus(BaseModel):
    """Status of a funded-account registration."""

    status: Literal["pending", "registered", "failed"]
    registration_id: str | None = None
    funded_account_id: str | None = None
    account_size: int
    estimated_time: str | None = None
    tx_hash: str | None = None
    message: str | None = None
