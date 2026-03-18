"""Registration models."""

from __future__ import annotations

from pydantic import BaseModel

TERMINAL_STATUSES = frozenset({"registered", "active", "failed", "eliminated"})
SUCCESS_STATUSES = frozenset({"registered", "active"})


class RegistrationStatus(BaseModel):
    """Status of a funded-account registration.

    Used both for purchase results (SDK-008) and status polling (SDK-009).
    The status endpoint returns ``{"status": ..., "hl_address": ...}``
    so fields like ``account_size`` are optional.
    """

    status: str
    hl_address: str | None = None
    registration_id: str | None = None
    funded_account_id: str | None = None
    account_size: int | None = None
    estimated_time: str | None = None
    tx_hash: str | None = None
    message: str | None = None

    @property
    def is_terminal(self) -> bool:
        """Whether this status represents a final state."""
        return self.status in TERMINAL_STATUSES

    @property
    def is_success(self) -> bool:
        """Whether this status represents a successful registration."""
        return self.status in SUCCESS_STATUSES
