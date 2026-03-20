"""Tests for SDK-012 validator-backed rules and trade validation."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from hyperscaled.exceptions import (
    AccountSuspendedError,
    DrawdownBreachError,
    ExposureLimitError,
    InsufficientBalanceError,
    LeverageLimitError,
    UnsupportedPairError,
)
from hyperscaled.models.account import BalanceStatus
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
    account_size = float(balance)
    capital_used_f = float(capital_used)
    total_leverage = capital_used_f / account_size if account_size else 0
    return {
        "status": status if status not in {"active", "admin"} else "success",
        "hl_address": VALID_ADDRESS,
        "account_size": account_size,
        "payout_address": VALID_ADDRESS,
        "positions": {
            "positions": [],
            "total_leverage": total_leverage,
        },
        "drawdown": {
            "ledger_max_drawdown": 0.95,
        },
        "challenge_progress": {
            "bucket": bucket,
            "drawdown_percent": drawdown_percent,
            "drawdown_limit_percent": drawdown_limit_percent,
            "drawdown_usage_percent": drawdown_usage_percent,
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
    client._validator_http = httpx.AsyncClient(
        transport=handler, base_url="https://validator.example.com"
    )
    client.config.set_value("wallet.hl_address", VALID_ADDRESS)
    return client


class TestRulesClient:
    async def test_supported_pairs_returns_list_of_strings(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = _trade_pairs_payload(
            {
                "trade_pair_id": "BTCUSD",
                "trade_pair": "BTC/USD",
                "trade_pair_category": "crypto",
                "max_leverage": 2.5,
            },
            {
                "trade_pair_id": "ETHUSD",
                "trade_pair": "ETH/USD",
                "trade_pair_category": "crypto",
                "max_leverage": 2.5,
            },
        )

        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json=payload)
            if request.url.path == "/trade-pairs"
            else httpx.Response(404, json={"error": "unknown"})
        )
        client = _make_client(tmp_path, monkeypatch, transport)

        pairs = await client.rules.supported_pairs_async()

        assert isinstance(pairs, list)
        assert len(pairs) == 2
        assert all(isinstance(p, str) for p in pairs)
        assert "BTC-USDC" in pairs
        assert "ETH-USDC" in pairs
        await client.close()

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
            if request.url.path == f"/hl-traders/{VALID_ADDRESS}":
                return httpx.Response(200, json=dashboard)
            if request.url.host == "api.hyperliquid.xyz":
                return httpx.Response(200, json={"BTC": "100000"})
            return httpx.Response(404, json={"error": "unknown"})

        client = _make_client(tmp_path, monkeypatch, httpx.MockTransport(handler))

        async def mock_balance(*_args: object, **_kwargs: object) -> BalanceStatus:
            return BalanceStatus(balance=Decimal("5000"), meets_minimum=True)

        client.account.check_balance_async = mock_balance  # type: ignore[assignment]

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

        with pytest.raises(UnsupportedPairError, match="Unsupported pair"):
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
            if request.url.path == f"/hl-traders/{VALID_ADDRESS}":
                return httpx.Response(200, json=dashboard)
            if request.url.host == "api.hyperliquid.xyz":
                return httpx.Response(200, json={"BTC": "100000"})
            return httpx.Response(404, json={"error": "unknown"})

        client = _make_client(tmp_path, monkeypatch, httpx.MockTransport(handler))

        async def mock_balance(*_args: object, **_kwargs: object) -> BalanceStatus:
            return BalanceStatus(balance=Decimal("5000"), meets_minimum=True)

        client.account.check_balance_async = mock_balance  # type: ignore[assignment]

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
            if request.url.path == f"/hl-traders/{VALID_ADDRESS}":
                return httpx.Response(200, json=dashboard)
            if request.url.host == "api.hyperliquid.xyz":
                return httpx.Response(200, json={"BTC": "100000"})
            return httpx.Response(404, json={"error": "unknown"})

        client = _make_client(tmp_path, monkeypatch, httpx.MockTransport(handler))

        async def mock_balance(*_args: object, **_kwargs: object) -> BalanceStatus:
            return BalanceStatus(balance=Decimal("5000"), meets_minimum=True)

        client.account.check_balance_async = mock_balance  # type: ignore[assignment]

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
            if request.url.path == f"/hl-traders/{VALID_ADDRESS}":
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
            if request.url.path == f"/hl-traders/{VALID_ADDRESS}":
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

    async def test_validate_trade_insufficient_balance(
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
            if request.url.path == f"/hl-traders/{VALID_ADDRESS}":
                return httpx.Response(200, json=dashboard)
            if request.url.host == "api.hyperliquid.xyz":
                return httpx.Response(200, json={"BTC": "100000"})
            return httpx.Response(404, json={"error": "unknown"})

        client = _make_client(tmp_path, monkeypatch, httpx.MockTransport(handler))

        async def low_balance(*_args: object, **_kwargs: object) -> BalanceStatus:
            return BalanceStatus(balance=Decimal("500"), meets_minimum=False)

        client.account.check_balance_async = low_balance  # type: ignore[assignment]

        with pytest.raises(InsufficientBalanceError, match="below the.*minimum"):
            await client.rules.validate_trade_async(
                pair="BTC-USDC",
                side="long",
                size=Decimal("0.01"),
                order_type="market",
            )

        await client.close()
