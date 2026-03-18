"""Tests for SDK-005 — entity miner discovery."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import cast

import httpx
import pytest
from typer.testing import CliRunner

from hyperscaled.cli.main import app
from hyperscaled.exceptions import HyperscaledError
from hyperscaled.models import EntityMiner, PricingTier, ProfitSplit
from hyperscaled.sdk.client import HyperscaledClient

runner = CliRunner()


def _make_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    handler: httpx.MockTransport | httpx.AsyncBaseTransport,
) -> HyperscaledClient:
    monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
    client = HyperscaledClient(base_url="https://api.example.com")
    client._http = httpx.AsyncClient(transport=handler, base_url="https://api.example.com")
    return client


def _sample_miner() -> EntityMiner:
    split = ProfitSplit(trader_pct=80, miner_pct=20)
    return EntityMiner(
        name="Vanta Trading",
        slug="vanta",
        pricing_tiers=[
            PricingTier(account_size=25_000, cost=Decimal("150.00"), profit_split=split),
            PricingTier(account_size=50_000, cost=Decimal("250.00"), profit_split=split),
        ],
        payout_cadence="weekly",
        available_account_sizes=[25_000, 50_000],
        brand_color="#3b82f6",
    )


class TestMinersClient:
    async def test_list_all_normalizes_current_entity_catalog_shape(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json=[
                    {
                        "name": "Vanta Trading",
                        "slug": "vanta",
                        "color": "#3b82f6",
                        "payoutCadenceDays": 7,
                        "tiers": [
                            {"accountSize": 25_000, "priceUsdc": 150, "profitSplit": 80},
                            {"accountSize": 50_000, "priceUsdc": 250, "profitSplit": 80},
                        ],
                    }
                ],
            )
        )
        client = _make_client(tmp_path, monkeypatch, transport)

        miners = await client.miners.list_all_async()

        assert len(miners) == 1
        miner = miners[0]
        assert miner.slug == "vanta"
        assert miner.payout_cadence == "weekly"
        assert miner.available_account_sizes == [25_000, 50_000]
        assert miner.brand_color == "#3b82f6"
        assert miner.pricing_tiers[0].profit_split.trader_pct == 80
        await client.close()

    async def test_list_all_falls_back_to_legacy_catalog_route(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/entity":
                return httpx.Response(404, json={"error": "not found"})
            if request.url.path == "/api/v1/miners":
                return httpx.Response(
                    200,
                    json=[
                        {
                            "name": "Vanta Trading",
                            "slug": "vanta",
                            "brand_color": "#3b82f6",
                            "payout_cadence": "weekly",
                            "available_account_sizes": [25_000],
                            "pricing_tiers": [
                                {
                                    "account_size": 25_000,
                                    "cost": "150.00",
                                    "profit_split": {"trader_pct": 80, "miner_pct": 20},
                                }
                            ],
                        }
                    ],
                )
            return httpx.Response(404, json={"error": "not found"})

        client = _make_client(tmp_path, monkeypatch, httpx.MockTransport(handler))

        miners = await client.miners.list_all_async()

        assert len(miners) == 1
        assert miners[0].slug == "vanta"
        await client.close()

    async def test_get_accepts_current_entity_catalog_shape(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json=[
                    {
                        "name": "Vanta Trading",
                        "slug": "vanta",
                        "color": "#3b82f6",
                        "payoutCadenceDays": 7,
                        "tiers": [{"accountSize": 25_000, "priceUsdc": 150, "profitSplit": 80}],
                    },
                    {
                        "name": "Zoku Trading",
                        "slug": "zoku",
                        "color": "#7c3aed",
                        "payoutCadenceDays": 14,
                        "tiers": [{"accountSize": 50_000, "priceUsdc": 250, "profitSplit": 75}],
                    },
                ],
            )
        )
        client = _make_client(tmp_path, monkeypatch, transport)

        miner = await client.miners.get_async("vanta")

        assert miner.slug == "vanta"
        assert miner.pricing_tiers[0].profit_split.miner_pct == 20
        await client.close()

    def test_list_all_sync_outside_event_loop(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json=[
                    {
                        "name": "Vanta Trading",
                        "slug": "vanta",
                        "color": "#3b82f6",
                        "payoutCadenceDays": 7,
                        "tiers": [{"accountSize": 25_000, "priceUsdc": 150, "profitSplit": 80}],
                    }
                ],
            )
        )
        client = _make_client(tmp_path, monkeypatch, transport)

        miners = cast(list[EntityMiner], client.miners.list_all())

        assert len(miners) == 1
        client.close_sync()

    async def test_get_missing_slug_raises_hyperscaled_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json=[
                    {
                        "name": "Vanta Trading",
                        "slug": "vanta",
                        "payout_cadence": "weekly",
                        "available_account_sizes": [25_000],
                        "pricing_tiers": [
                            {
                                "account_size": 25_000,
                                "cost": "150.00",
                                "profit_split": {"trader_pct": 80, "miner_pct": 20},
                            }
                        ],
                    }
                ],
            )
        )
        client = _make_client(tmp_path, monkeypatch, transport)

        with pytest.raises(HyperscaledError, match="missing"):
            await client.miners.get_async("missing")

        await client.close()

    async def test_compare_fetches_requested_slugs_from_catalog(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen_paths: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen_paths.append(request.url.path)
            return httpx.Response(
                200,
                json=[
                    {
                        "name": "Vanta Trading",
                        "slug": "vanta",
                        "payout_cadence": "weekly",
                        "available_account_sizes": [25_000],
                        "pricing_tiers": [
                            {
                                "account_size": 25_000,
                                "cost": "150.00",
                                "profit_split": {"trader_pct": 80, "miner_pct": 20},
                            }
                        ],
                    },
                    {
                        "name": "Zoku Trading",
                        "slug": "zoku",
                        "payout_cadence": "weekly",
                        "available_account_sizes": [25_000],
                        "pricing_tiers": [
                            {
                                "account_size": 25_000,
                                "cost": "175.00",
                                "profit_split": {"trader_pct": 75, "miner_pct": 25},
                            }
                        ],
                    },
                ],
            )

        client = _make_client(tmp_path, monkeypatch, httpx.MockTransport(handler))

        miners = await client.miners.compare_async(["vanta", "zoku"])

        assert [miner.slug for miner in miners] == ["vanta", "zoku"]
        assert seen_paths == ["/api/entity"]
        await client.close()

    async def test_compare_missing_slug_raises_hyperscaled_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json=[
                    {
                        "name": "Vanta Trading",
                        "slug": "vanta",
                        "payout_cadence": "weekly",
                        "available_account_sizes": [25_000],
                        "pricing_tiers": [
                            {
                                "account_size": 25_000,
                                "cost": "150.00",
                                "profit_split": {"trader_pct": 80, "miner_pct": 20},
                            }
                        ],
                    }
                ],
            )
        )
        client = _make_client(tmp_path, monkeypatch, transport)

        with pytest.raises(HyperscaledError, match="missing"):
            await client.miners.compare_async(["vanta", "missing"])

        await client.close()


class _FakeMinersClient:
    def __init__(self, miners: list[EntityMiner]) -> None:
        self._miners = miners

    def list_all(self) -> list[EntityMiner]:
        return self._miners

    def get(self, slug: str) -> EntityMiner:
        for miner in self._miners:
            if miner.slug == slug:
                return miner
        raise HyperscaledError(f"Miner '{slug}' not found.")

    def compare(self, slugs: list[str] | None = None) -> list[EntityMiner]:
        if slugs is None:
            return self._miners
        return [self.get(slug) for slug in slugs]


class _FakeClient:
    def __init__(self, miners: list[EntityMiner]) -> None:
        self.miners = _FakeMinersClient(miners)


class TestMinersCLI:
    def test_miners_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "hyperscaled.cli.miners.HyperscaledClient",
            lambda: _FakeClient([_sample_miner()]),
        )

        result = runner.invoke(app, ["miners", "list"])

        assert result.exit_code == 0
        assert "Entity Miners" in result.output
        assert "vanta" in result.output
        assert "Weekly" in result.output

    def test_miners_info_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "hyperscaled.cli.miners.HyperscaledClient",
            lambda: _FakeClient([_sample_miner()]),
        )

        result = runner.invoke(app, ["miners", "info", "vanta", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["slug"] == "vanta"
        assert payload["pricing_tiers"][0]["profit_split"]["trader_pct"] == 80

    def test_miners_compare(self, monkeypatch: pytest.MonkeyPatch) -> None:
        miner = _sample_miner()
        monkeypatch.setattr(
            "hyperscaled.cli.miners.HyperscaledClient",
            lambda: _FakeClient(
                [miner, miner.model_copy(update={"slug": "zoku", "name": "Zoku Trading"})]
            ),
        )

        result = runner.invoke(app, ["miners", "compare"])

        assert result.exit_code == 0
        assert "Entity Miners" in result.output
        assert "zoku" in result.output
