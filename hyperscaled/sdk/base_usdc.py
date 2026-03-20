"""USDC balance on Base via public JSON-RPC (no web3 dependency)."""

from __future__ import annotations

from decimal import Decimal

import httpx

from hyperscaled.exceptions import HyperscaledError

# Circle USDC on Base mainnet / Base Sepolia
_BASE_MAINNET_USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
_BASE_SEPOLIA_USDC = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"

_BASE_MAINNET_RPC = "https://mainnet.base.org"
_BASE_SEPOLIA_RPC = "https://sepolia.base.org"

_USDC_DECIMALS = 6


def _balance_of_call_data(holder: str) -> str:
    addr = holder.removeprefix("0x").removeprefix("0X").lower()
    if len(addr) != 40 or any(c not in "0123456789abcdef" for c in addr):
        raise ValueError(f"Invalid EVM address: {holder!r}")
    return "0x70a08231" + addr.rjust(64, "0")


async def fetch_base_usdc_balance(
    wallet_address: str,
    *,
    testnet: bool = False,
    timeout: float = 30.0,
) -> Decimal:
    """Return USDC balance on Base (or Base Sepolia when *testnet* is True)."""
    rpc_url = _BASE_SEPOLIA_RPC if testnet else _BASE_MAINNET_RPC
    token = _BASE_SEPOLIA_USDC if testnet else _BASE_MAINNET_USDC
    payload: dict[str, object] = {
        "jsonrpc": "2.0",
        "method": "eth_call",
        "params": [
            {"to": token, "data": _balance_of_call_data(wallet_address)},
            "latest",
        ],
        "id": 1,
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(rpc_url, json=payload)
            resp.raise_for_status()
            body = resp.json()
    except httpx.HTTPError as exc:
        raise HyperscaledError(f"Base USDC balance request failed: {exc}") from exc

    err = body.get("error")
    if err:
        msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
        raise HyperscaledError(f"Base RPC error: {msg}")

    raw = body.get("result")
    if not isinstance(raw, str) or not raw.startswith("0x"):
        raise HyperscaledError("Unexpected Base RPC balance response")

    value = int(raw, 16)
    return Decimal(value) / (10**_USDC_DECIMALS)
