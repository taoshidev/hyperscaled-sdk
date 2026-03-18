"""Pair normalization and validation utilities.

The SDK's public API uses ``BTC-USDC``, the Hyperliquid SDK wants ``BTC``,
and Vanta internals use ``BTCUSD``.  This module keeps the mapping in one place.
"""

from __future__ import annotations

SUPPORTED_PAIRS = frozenset({
    "BTC-USDC",
    "ETH-USDC",
    "SOL-USDC",
    "XRP-USDC",
    "DOGE-USDC",
    "ADA-USDC",
})


def validate_pair(pair: str) -> None:
    """Raise ``ValueError`` if *pair* is not in the supported set."""
    normalized = pair.upper()
    if normalized not in SUPPORTED_PAIRS:
        raise ValueError(
            f"Unsupported pair {pair!r}. "
            f"Supported pairs: {', '.join(sorted(SUPPORTED_PAIRS))}"
        )


def normalize_pair_to_hl(pair: str) -> str:
    """Convert SDK pair format to Hyperliquid asset name.

    ``'BTC-USDC'`` → ``'BTC'``
    """
    return pair.split("-")[0].upper()


def normalize_pair_to_vanta(pair: str) -> str:
    """Convert SDK pair format to Vanta ``trade_pair_id``.

    ``'BTC-USDC'`` → ``'BTCUSD'``
    """
    return f"{pair.split('-')[0].upper()}USD"
