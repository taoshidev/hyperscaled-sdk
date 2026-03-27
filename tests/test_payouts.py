"""Tests for PayoutsClient SDK and CLI."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from typer.testing import CliRunner

from hyperscaled.cli.main import app
from hyperscaled.exceptions import HyperscaledError
from hyperscaled.models.payout import Payout
from hyperscaled.sdk.client import HyperscaledClient

VALID_ADDRESS = "0x" + "a1" * 20
runner = CliRunner()


def _make_dashboard_response(
    payouts: list[dict] | None = None,
    pending_payout: dict | None = None,
) -> httpx.Response:
    """Construct a fake validator dashboard response with payout data."""
    dashboard: dict = {
        "subaccount_info": {
            "synthetic_hotkey": "entity_hotkey_0",
            "subaccount_uuid": "uuid-1",
            "subaccount_id": 0,
            "asset_class": "crypto",
            "account_size": 50000,
            "status": "active",
            "created_at_ms": 1700000000000,
            "eliminated_at_ms": None,
            "hl_address": VALID_ADDRESS,
        },
    }
    if payouts is not None:
        dashboard["payouts"] = payouts
    if pending_payout is not None:
        dashboard["pending_payout"] = pending_payout
    body = {
        "status": "success",
        "dashboard": dashboard,
        "timestamp": 1710000000000,
    }
    return httpx.Response(
        200,
        json=body,
        request=httpx.Request("GET", f"https://validator.test/hl-traders/{VALID_ADDRESS}"),
    )


def _make_404_response() -> httpx.Response:
    return httpx.Response(
        404,
        json={"error": "not found"},
        request=httpx.Request("GET", f"https://validator.test/hl-traders/{VALID_ADDRESS}"),
    )


def _make_500_response() -> httpx.Response:
    return httpx.Response(
        500,
        json={"error": "internal"},
        request=httpx.Request("GET", f"https://validator.test/hl-traders/{VALID_ADDRESS}"),
    )


SAMPLE_PAYOUTS = [
    {
        "date": "2026-03-15T12:00:00Z",
        "amount": "250.50",
        "token": "USDC",
        "network": "Hyperliquid",
        "tx_hash": "0xabc123def456",
        "status": "completed",
    },
    {
        "date": "2026-03-10T08:30:00Z",
        "amount": "100.00",
        "token": "USDC",
        "network": "Hyperliquid",
        "tx_hash": "0xdef789",
        "status": "completed",
    },
]

SAMPLE_PENDING = {
    "date": "2026-03-20T00:00:00Z",
    "amount": "175.25",
    "token": "USDC",
    "network": "Hyperliquid",
    "tx_hash": None,
    "status": "pending",
}


# ── SDK: PayoutsClient.history_async ──────────────────────────


class TestPayoutsHistory:
    async def test_history_returns_payouts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient(hl_wallet=VALID_ADDRESS)
        await client.open()

        mock_response = _make_dashboard_response(payouts=SAMPLE_PAYOUTS)
        client.validator_http.get = AsyncMock(return_value=mock_response)

        payouts = await client.payouts.history_async()

        assert len(payouts) == 2
        assert payouts[0].amount == Decimal("250.50")
        assert payouts[0].status == "completed"
        assert payouts[0].token == "USDC"
        assert payouts[0].tx_hash == "0xabc123def456"
        assert payouts[1].amount == Decimal("100.00")

        await client.close()

    async def test_history_empty_when_no_payouts_field(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient(hl_wallet=VALID_ADDRESS)
        await client.open()

        mock_response = _make_dashboard_response()  # no payouts field
        client.validator_http.get = AsyncMock(return_value=mock_response)

        payouts = await client.payouts.history_async()
        assert payouts == []

        await client.close()

    async def test_history_empty_list(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient(hl_wallet=VALID_ADDRESS)
        await client.open()

        mock_response = _make_dashboard_response(payouts=[])
        client.validator_http.get = AsyncMock(return_value=mock_response)

        payouts = await client.payouts.history_async()
        assert payouts == []

        await client.close()

    async def test_history_404_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient(hl_wallet=VALID_ADDRESS)
        await client.open()

        client.validator_http.get = AsyncMock(return_value=_make_404_response())

        with pytest.raises(HyperscaledError, match="No validator dashboard"):
            await client.payouts.history_async()

        await client.close()

    async def test_history_500_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient(hl_wallet=VALID_ADDRESS)
        await client.open()

        client.validator_http.get = AsyncMock(return_value=_make_500_response())

        with pytest.raises(HyperscaledError, match="Failed to fetch validator dashboard"):
            await client.payouts.history_async()

        await client.close()

    async def test_history_network_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient(hl_wallet=VALID_ADDRESS)
        await client.open()

        client.validator_http.get = AsyncMock(
            side_effect=httpx.ConnectError("connection refused")
        )

        with pytest.raises(HyperscaledError, match="Failed to fetch validator dashboard"):
            await client.payouts.history_async()

        await client.close()

    async def test_history_missing_wallet(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient()

        with pytest.raises(HyperscaledError, match="No Hyperliquid wallet"):
            await client.payouts.history_async()


# ── SDK: PayoutsClient.pending_async ──────────────────────────


class TestPayoutsPending:
    async def test_pending_from_dedicated_field(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient(hl_wallet=VALID_ADDRESS)
        await client.open()

        mock_response = _make_dashboard_response(pending_payout=SAMPLE_PENDING)
        client.validator_http.get = AsyncMock(return_value=mock_response)

        payout = await client.payouts.pending_async()

        assert payout is not None
        assert payout.status == "pending"
        assert payout.amount == Decimal("175.25")

        await client.close()

    async def test_pending_from_payouts_list(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient(hl_wallet=VALID_ADDRESS)
        await client.open()

        payouts_with_pending = SAMPLE_PAYOUTS + [SAMPLE_PENDING]
        mock_response = _make_dashboard_response(payouts=payouts_with_pending)
        client.validator_http.get = AsyncMock(return_value=mock_response)

        payout = await client.payouts.pending_async()

        assert payout is not None
        assert payout.status == "pending"
        assert payout.amount == Decimal("175.25")

        await client.close()

    async def test_pending_none_when_all_completed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient(hl_wallet=VALID_ADDRESS)
        await client.open()

        mock_response = _make_dashboard_response(payouts=SAMPLE_PAYOUTS)
        client.validator_http.get = AsyncMock(return_value=mock_response)

        payout = await client.payouts.pending_async()
        assert payout is None

        await client.close()

    async def test_pending_none_when_no_payouts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient(hl_wallet=VALID_ADDRESS)
        await client.open()

        mock_response = _make_dashboard_response()
        client.validator_http.get = AsyncMock(return_value=mock_response)

        payout = await client.payouts.pending_async()
        assert payout is None

        await client.close()


# ── CLI: hyperscaled payouts history ──────────────────────────


class TestPayoutsHistoryCLI:
    def test_history_table_output(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        sample = [
            Payout(
                date=datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc),
                amount=Decimal("250.50"),
                token="USDC",
                network="Hyperliquid",
                tx_hash="0xabc123def456",
                status="completed",
            ),
        ]
        with patch(
            "hyperscaled.sdk.payouts.PayoutsClient.history",
            return_value=sample,
        ):
            result = runner.invoke(app, ["payouts", "history"])

        assert result.exit_code == 0
        assert "250.50" in result.output
        assert "USDC" in result.output

    def test_history_json_output(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        sample = [
            Payout(
                date=datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc),
                amount=Decimal("250.50"),
                token="USDC",
                network="Hyperliquid",
                tx_hash="0xabc123",
                status="completed",
            ),
        ]
        with patch(
            "hyperscaled.sdk.payouts.PayoutsClient.history",
            return_value=sample,
        ):
            result = runner.invoke(app, ["payouts", "history", "--json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["amount"] == "250.50"
        assert data[0]["status"] == "completed"

    def test_history_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        with patch(
            "hyperscaled.sdk.payouts.PayoutsClient.history",
            return_value=[],
        ):
            result = runner.invoke(app, ["payouts", "history"])

        assert result.exit_code == 0
        assert "No payouts found" in result.output

    def test_history_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        with patch(
            "hyperscaled.sdk.payouts.PayoutsClient.history",
            side_effect=HyperscaledError("No Hyperliquid wallet configured."),
        ):
            result = runner.invoke(app, ["payouts", "history"])

        assert result.exit_code == 1
        assert "No Hyperliquid wallet configured" in result.output


# ── CLI: hyperscaled payouts pending ──────────────────────────


class TestPayoutsPendingCLI:
    def test_pending_shows_payout(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        sample = Payout(
            date=datetime(2026, 3, 20, 0, 0, tzinfo=timezone.utc),
            amount=Decimal("175.25"),
            token="USDC",
            network="Hyperliquid",
            tx_hash=None,
            status="pending",
        )
        with patch(
            "hyperscaled.sdk.payouts.PayoutsClient.pending",
            return_value=sample,
        ):
            result = runner.invoke(app, ["payouts", "pending"])

        assert result.exit_code == 0
        assert "175.25" in result.output
        assert "pending" in result.output

    def test_pending_json_output(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        sample = Payout(
            date=datetime(2026, 3, 20, 0, 0, tzinfo=timezone.utc),
            amount=Decimal("175.25"),
            token="USDC",
            network="Hyperliquid",
            tx_hash=None,
            status="pending",
        )
        with patch(
            "hyperscaled.sdk.payouts.PayoutsClient.pending",
            return_value=sample,
        ):
            result = runner.invoke(app, ["payouts", "pending", "--json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["amount"] == "175.25"
        assert data["status"] == "pending"

    def test_pending_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        with patch(
            "hyperscaled.sdk.payouts.PayoutsClient.pending",
            return_value=None,
        ):
            result = runner.invoke(app, ["payouts", "pending"])

        assert result.exit_code == 0
        assert "No pending payout" in result.output

    def test_pending_none_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        with patch(
            "hyperscaled.sdk.payouts.PayoutsClient.pending",
            return_value=None,
        ):
            result = runner.invoke(app, ["payouts", "pending", "--json"])

        assert result.exit_code == 0
        assert json.loads(result.output) is None

    def test_pending_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        with patch(
            "hyperscaled.sdk.payouts.PayoutsClient.pending",
            side_effect=HyperscaledError("No Hyperliquid wallet configured."),
        ):
            result = runner.invoke(app, ["payouts", "pending"])

        assert result.exit_code == 1
        assert "No Hyperliquid wallet configured" in result.output
