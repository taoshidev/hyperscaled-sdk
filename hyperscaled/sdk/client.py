"""HyperscaledClient — main entry point for programmatic SDK use.

Wired in SDK-003.
"""

from __future__ import annotations


class HyperscaledClient:
    """Main client for the Hyperscaled SDK.

    Full implementation in SDK-003. Currently a stub so that
    ``from hyperscaled import HyperscaledClient`` works immediately.
    """

    def __init__(
        self,
        *,
        hl_wallet: str | None = None,
        payout_wallet: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self._hl_wallet = hl_wallet
        self._payout_wallet = payout_wallet
        self._base_url = base_url
