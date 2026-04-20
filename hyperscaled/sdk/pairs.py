"""Pair normalization utilities.

The SDK accepts several pair formats and normalizes them to the target
needed by each downstream system:

- SDK format: ``BTC-USDC``
- Validator format: ``BTCUSD``
- Slash format: ``BTC/USD``
- Raw asset name: ``BTC``, ``AAPL``

The canonical, up-to-date list of allowed pairs is served by the validator
at ``GET /trade-pairs`` and is exposed via ``HyperscaledClient.rules``
(see ``supported_pairs()`` and ``validate_trade()``).
"""

from __future__ import annotations


def _clean(pair: str) -> str:
    raw = pair.strip().upper()
    if not raw:
        raise ValueError("Pair must be a non-empty string")
    return raw


def normalize_pair_to_hl(pair: str) -> str:
    """Return the Hyperliquid asset name for *pair*.

    Examples
    --------
    ``'BTC-USDC'`` → ``'BTC'``, ``'BTC/USD'`` → ``'BTC'``,
    ``'BTCUSD'`` → ``'BTC'``, ``'AAPL'`` → ``'AAPL'``.
    """
    raw = _clean(pair)
    if "/" in raw:
        return raw.split("/", 1)[0]
    if "-" in raw:
        return raw.split("-", 1)[0]
    if raw.endswith("USDC") and raw != "USDC":
        return raw[:-4]
    if raw.endswith("USD") and raw != "USD":
        return raw[:-3]
    return raw


def normalize_pair_to_vanta(pair: str) -> str:
    """Return the validator ``trade_pair_id`` for *pair*.

    Examples
    --------
    ``'BTC-USDC'`` → ``'BTCUSD'``, ``'BTC/USD'`` → ``'BTCUSD'``,
    ``'BTCUSD'`` → ``'BTCUSD'``, ``'AAPL'`` → ``'AAPL'``.
    """
    raw = _clean(pair)
    if "/" in raw:
        base, quote = raw.split("/", 1)
        return f"{base}{quote}"
    if "-" in raw:
        base, quote = raw.split("-", 1)
        if quote == "USDC":
            quote = "USD"
        return f"{base}{quote}"
    return raw
