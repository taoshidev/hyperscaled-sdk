"""Tests for SDK-012 validator-backed rules and trade validation."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from hyperscaled.exceptions import (
    AccountSuspendedError,
    DrawdownBreachError,
    ExposureLimitError,
    LeverageLimitError,
    TemporarilyHaltedPairError,
)
from hyperscaled.sdk.client import HyperscaledClient

VALID_ADDRESS = "0x" + "a1" * 20


def _trade_pairs_payload(*pairs: dict[str, object]) -> dict[str, object]:
    return {
        "allowed_trade_pairs": list(pairs),
        "allowed_trade_pair_ids": [str(pair["trade_pair_id"]) for pair in pairs],
        "total_trade_pairs": len(pairs),
        "timestamp": 1,
    }


def _dashboard_payload(
    *,
    status: str = "active",
    balance: str = "10000",
    capital_used: str = "1000",
    bucket: str = "SUBACCOUNT_FUNDED",
    drawdown_percent: str = "1.0",
    drawdown_limit_percent: str = "5.0",
    drawdown_usage_percent: str = "20.0",
) -> dict[str, object]:
    return {
        "status": "success",
        "hl_address": VALID_ADDRESS,
        "dashboard": {
            "subaccount_info": {
                "status": status,
                "account_size": 10000,
                "hl_address": VALID_ADDRESS,
                "payout_address": VALID_ADDRESS,
            },
            "challenge_period": {
                "bucket": bucket,
                "drawdown_percent": drawdown_percent,
                "drawdown_limit_percent": drawdown_limit_percent,
                "drawdown_usage_percent": drawdown_usage_percent,
            },
            "account_size_data": {
                "balance": balance,
                "capital_used": capital_used,
                "account_size": 10000,
            },
        },
        "timestamp": 1,
    }


def _make_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    handler: httpx.MockTransport,
) -> HyperscaledClient:
    monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
    client = HyperscaledClient(base_url="https://api.example.com")
    client._http = httpx.AsyncClient(transport=handler, base_url="https://api.example.com")
    client.config.set_value("wallet.hl_address", VALID_ADDRESS)
    return client


class TestRulesClient:
    async def test_list_all_returns_pair_and_leverage_rules(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = _trade_pairs_payload(
            {
                "trade_pair_id": "BTCUSD",
                "trade_pair": "BTC/USD",
                "trade_pair_category": "crypto",
                "max_leverage": 2.5,
            }
        )

        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json=payload)
            if request.url.path == "/trade-pairs"
            else httpx.Response(404, json={"error": "unknown"})
        )
        client = _make_client(tmp_path, monkeypatch, transport)

        rules = await client.rules.list_all_async()

        assert len(rules) == 3
        assert any(rule.rule_id.endswith("BTCUSD") for rule in rules)
        assert any(rule.limit == "2.5" for rule in rules)
        await client.close()

    async def test_validate_trade_success(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        trade_pairs = _trade_pairs_payload(
            {
                "trade_pair_id": "BTCUSD",
                "trade_pair": "BTC/USD",
                "trade_pair_category": "crypto",
                "max_leverage": 2.5,
            }
        )
        dashboard = _dashboard_payload()

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/trade-pairs":
                return httpx.Response(200, json=trade_pairs)
            if request.url.path == f"/hl/{VALID_ADDRESS}/dashboard":
                return httpx.Response(200, json=dashboard)
            if request.url.host == "api.hyperliquid.xyz":
                return httpx.Response(200, json={"BTC": "100000"})
            return httpx.Response(404, json={"error": "unknown"})

        client = _make_client(tmp_path, monkeypatch, httpx.MockTransport(handler))

        result = await client.rules.validate_trade_async(
            pair="BTC-USDC",
            side="long",
            size=Decimal("0.01"),
            order_type="market",
        )

        assert result.valid is True
        assert result.violations == []
        await client.close()

    async def test_validate_trade_halted_pair(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        trade_pairs = _trade_pairs_payload(
            {
                "trade_pair_id": "ETHUSD",
                "trade_pair": "ETH/USD",
                "trade_pair_category": "crypto",
                "max_leverage": 2.5,
            }
        )
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json=trade_pairs)
            if request.url.path == "/trade-pairs"
            else httpx.Response(404, json={"error": "unknown"})
        )
        client = _make_client(tmp_path, monkeypatch, transport)

        with pytest.raises(TemporarilyHaltedPairError, match="allowed trade-pair list"):
            await client.rules.validate_trade_async(
                pair="BTC-USDC",
                side="long",
                size=Decimal("0.01"),
                order_type="market",
            )
        await client.close()

    async def test_validate_trade_leverage_limit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        trade_pairs = _trade_pairs_payload(
            {
                "trade_pair_id": "BTCUSD",
                "trade_pair": "BTC/USD",
                "trade_pair_category": "crypto",
                "max_leverage": 2.5,
            }
        )
        dashboard = _dashboard_payload(balance="10000", capital_used="0")

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/trade-pairs":
                return httpx.Response(200, json=trade_pairs)
            if request.url.path == f"/hl/{VALID_ADDRESS}/dashboard":
                return httpx.Response(200, json=dashboard)
            if request.url.host == "api.hyperliquid.xyz":
                return httpx.Response(200, json={"BTC": "100000"})
            return httpx.Response(404, json={"error": "unknown"})

        client = _make_client(tmp_path, monkeypatch, httpx.MockTransport(handler))

        with pytest.raises(LeverageLimitError, match="exceeds the validator limit"):
            await client.rules.validate_trade_async(
                pair="BTC-USDC",
                side="long",
                size=Decimal("1"),
                order_type="market",
            )
        await client.close()

    async def test_validate_trade_exposure_limit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        trade_pairs = _trade_pairs_payload(
            {
                "trade_pair_id": "BTCUSD",
                "trade_pair": "BTC/USD",
                "trade_pair_category": "crypto",
                "max_leverage": 2.5,
            }
        )
        dashboard = _dashboard_payload(balance="10000", capital_used="49000")

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/trade-pairs":
                return httpx.Response(200, json=trade_pairs)
            if request.url.path == f"/hl/{VALID_ADDRESS}/dashboard":
                return httpx.Response(200, json=dashboard)
            if request.url.host == "api.hyperliquid.xyz":
                return httpx.Response(200, json={"BTC": "100000"})
            return httpx.Response(404, json={"error": "unknown"})

        client = _make_client(tmp_path, monkeypatch, httpx.MockTransport(handler))

        with pytest.raises(ExposureLimitError, match="portfolio exposure limit"):
            await client.rules.validate_trade_async(
                pair="BTC-USDC",
                side="long",
                size=Decimal("0.02"),
                order_type="market",
            )
        await client.close()

    async def test_validate_trade_account_status(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        trade_pairs = _trade_pairs_payload(
            {
                "trade_pair_id": "BTCUSD",
                "trade_pair": "BTC/USD",
                "trade_pair_category": "crypto",
                "max_leverage": 2.5,
            }
        )
        dashboard = _dashboard_payload(status="pending")

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/trade-pairs":
                return httpx.Response(200, json=trade_pairs)
            if request.url.path == f"/hl/{VALID_ADDRESS}/dashboard":
                return httpx.Response(200, json=dashboard)
            return httpx.Response(404, json={"error": "unknown"})

        client = _make_client(tmp_path, monkeypatch, httpx.MockTransport(handler))

        with pytest.raises(AccountSuspendedError, match="not currently tradeable"):
            await client.rules.validate_trade_async(
                pair="BTC-USDC",
                side="long",
                size=Decimal("0.01"),
                order_type="limit",
                price=Decimal("100000"),
            )
        await client.close()

    async def test_validate_trade_drawdown_breach(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        trade_pairs = _trade_pairs_payload(
            {
                "trade_pair_id": "BTCUSD",
                "trade_pair": "BTC/USD",
                "trade_pair_category": "crypto",
                "max_leverage": 2.5,
            }
        )
        dashboard = _dashboard_payload(
            drawdown_percent="5.0",
            drawdown_limit_percent="5.0",
            drawdown_usage_percent="100.0",
        )

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/trade-pairs":
                return httpx.Response(200, json=trade_pairs)
            if request.url.path == f"/hl/{VALID_ADDRESS}/dashboard":
                return httpx.Response(200, json=dashboard)
            return httpx.Response(404, json={"error": "unknown"})

        client = _make_client(tmp_path, monkeypatch, httpx.MockTransport(handler))

        with pytest.raises(DrawdownBreachError, match="drawdown limit"):
            await client.rules.validate_trade_async(
                pair="BTC-USDC",
                side="long",
                size=Decimal("0.01"),
                order_type="limit",
                price=Decimal("100000"),
            )
        await client.close()
