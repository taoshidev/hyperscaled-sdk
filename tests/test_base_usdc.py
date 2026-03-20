"""Tests for Base USDC JSON-RPC balance helper."""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest

from hyperscaled.exceptions import HyperscaledError
from hyperscaled.sdk.base_usdc import _balance_of_call_data, fetch_base_usdc_balance


def test_balance_of_call_data() -> None:
    data = _balance_of_call_data("0xAbCdEf0123456789AbCdEf0123456789AbCdEf01")
    assert data.startswith("0x70a08231")
    assert data.endswith("abcdef0123456789abcdef0123456789abcdef01")


def test_balance_of_call_data_rejects_invalid() -> None:
    with pytest.raises(ValueError, match="Invalid"):
        _balance_of_call_data("0xbad")


class _FakeAsyncClient:
    """Minimal async context manager matching httpx.AsyncClient usage in base_usdc."""

    def __init__(self, response: httpx.Response) -> None:
        self._response = response

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(self, url: str, json: object | None = None) -> httpx.Response:
        return self._response


@pytest.mark.asyncio
async def test_fetch_base_usdc_balance_success(monkeypatch: pytest.MonkeyPatch) -> None:
    # 100 USDC with 6 decimals
    hundred_usdc = "0x0000000000000000000000000000000000000000000000000000000005f5e100"
    req = httpx.Request("POST", "https://mainnet.base.org/")
    resp = httpx.Response(
        200,
        json={"jsonrpc": "2.0", "id": 1, "result": hundred_usdc},
        request=req,
    )

    def _client_factory(**kwargs: object) -> _FakeAsyncClient:
        return _FakeAsyncClient(resp)

    monkeypatch.setattr("hyperscaled.sdk.base_usdc.httpx.AsyncClient", _client_factory)

    bal = await fetch_base_usdc_balance("0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266")
    assert bal == Decimal("100")


@pytest.mark.asyncio
async def test_fetch_base_usdc_balance_rpc_error(monkeypatch: pytest.MonkeyPatch) -> None:
    req = httpx.Request("POST", "https://mainnet.base.org/")
    resp = httpx.Response(
        200,
        json={"jsonrpc": "2.0", "id": 1, "error": {"message": "reverted"}},
        request=req,
    )

    monkeypatch.setattr(
        "hyperscaled.sdk.base_usdc.httpx.AsyncClient",
        lambda **kw: _FakeAsyncClient(resp),
    )

    with pytest.raises(HyperscaledError, match="reverted"):
        await fetch_base_usdc_balance("0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266")
