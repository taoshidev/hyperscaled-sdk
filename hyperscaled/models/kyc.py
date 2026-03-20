"""Pydantic models for KYC (SumSub) verification data."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class KycInfo(BaseModel):
    """KYC verification status for a wallet."""

    wallet: str
    kyc_status: Literal["none", "pending", "approved", "rejected"]
    verified: bool
    verified_at: datetime | None = None


class KycTokenResponse(BaseModel):
    """Response from creating a SumSub applicant / fetching an SDK token."""

    token: str
    kyc_status: Literal["none", "pending", "approved", "rejected"]
