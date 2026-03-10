"""Account management SDK interface."""

from __future__ import annotations

from hyperscaled.sdk.config import is_valid_hl_address


class AccountClient:
    """Account-related helpers for Hyperliquid wallet setup flows."""

    def __init__(self, client: object) -> None:
        self._client = client

    def validate_wallet(self, address: str) -> bool:
        """Return ``True`` when ``address`` is a valid Hyperliquid wallet format."""
        return is_valid_hl_address(address)
