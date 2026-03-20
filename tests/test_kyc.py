"""Tests for KYCClient SDK and CLI."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from typer.testing import CliRunner

from hyperscaled.cli.main import app
from hyperscaled.exceptions import HyperscaledError
from hyperscaled.models.kyc import KycInfo, KycTokenResponse
from hyperscaled.sdk.client import HyperscaledClient

VALID_ADDRESS = "0x" + "a1" * 20
runner = CliRunner()


def _make_status_response(
    kyc_status: str = "none",
    verified: bool = False,
    verified_at: str | None = None,
) -> httpx.Response:
    body = {
        "wallet": VALID_ADDRESS,
        "kycStatus": kyc_status,
        "verified": verified,
        "verifiedAt": verified_at,
    }
    return httpx.Response(
        200,
        json=body,
        request=httpx.Request("GET", "https://app.test/api/kyc/status"),
    )


def _make_token_response(
    kyc_status: str = "pending",
    token: str = "sumsub-token-abc",
) -> httpx.Response:
    return httpx.Response(
        200,
        json={"token": token, "kycStatus": kyc_status},
        request=httpx.Request("POST", "https://app.test/api/kyc/token"),
    )


def _make_error_response(status_code: int, method: str = "GET") -> httpx.Response:
    url = "https://app.test/api/kyc/status" if method == "GET" else "https://app.test/api/kyc/token"
    return httpx.Response(
        status_code,
        json={"error": "err"},
        request=httpx.Request(method, url),
    )


# ── SDK: KYCClient.status_async ──────────────────────────


class TestKycStatus:
    async def test_status_none(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient(hl_wallet=VALID_ADDRESS)
        await client.open()

        client.http.get = AsyncMock(return_value=_make_status_response("none", False))

        info = await client.kyc.status_async()
        assert info.kyc_status == "none"
        assert info.verified is False
        assert info.verified_at is None

        await client.close()

    async def test_status_pending(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient(hl_wallet=VALID_ADDRESS)
        await client.open()

        client.http.get = AsyncMock(return_value=_make_status_response("pending", False))

        info = await client.kyc.status_async()
        assert info.kyc_status == "pending"
        assert info.verified is False

        await client.close()

    async def test_status_approved(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient(hl_wallet=VALID_ADDRESS)
        await client.open()

        client.http.get = AsyncMock(
            return_value=_make_status_response("approved", True, "2026-03-15T10:00:00Z")
        )

        info = await client.kyc.status_async()
        assert info.kyc_status == "approved"
        assert info.verified is True
        assert info.verified_at is not None

        await client.close()

    async def test_status_rejected(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient(hl_wallet=VALID_ADDRESS)
        await client.open()

        client.http.get = AsyncMock(return_value=_make_status_response("rejected", False))

        info = await client.kyc.status_async()
        assert info.kyc_status == "rejected"
        assert info.verified is False

        await client.close()

    async def test_status_404_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient(hl_wallet=VALID_ADDRESS)
        await client.open()

        client.http.get = AsyncMock(return_value=_make_error_response(404))

        with pytest.raises(HyperscaledError, match="KYC request failed"):
            await client.kyc.status_async()

        await client.close()

    async def test_status_500_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient(hl_wallet=VALID_ADDRESS)
        await client.open()

        client.http.get = AsyncMock(return_value=_make_error_response(500))

        with pytest.raises(HyperscaledError, match="Failed to fetch KYC status"):
            await client.kyc.status_async()

        await client.close()

    async def test_status_missing_wallet(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient()

        with pytest.raises(HyperscaledError, match="No Hyperliquid wallet"):
            await client.kyc.status_async()


# ── SDK: KYCClient.is_verified_async ──────────────────────────


class TestKycIsVerified:
    async def test_is_verified_true(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient(hl_wallet=VALID_ADDRESS)
        await client.open()

        client.http.get = AsyncMock(
            return_value=_make_status_response("approved", True, "2026-03-15T10:00:00Z")
        )

        assert await client.kyc.is_verified_async() is True

        await client.close()

    async def test_is_verified_false(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient(hl_wallet=VALID_ADDRESS)
        await client.open()

        client.http.get = AsyncMock(return_value=_make_status_response("pending", False))

        assert await client.kyc.is_verified_async() is False

        await client.close()


# ── SDK: KYCClient.start_async ──────────────────────────


class TestKycStart:
    async def test_start_success(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient(hl_wallet=VALID_ADDRESS)
        await client.open()

        client.http.post = AsyncMock(return_value=_make_token_response())

        resp = await client.kyc.start_async()
        assert resp.token == "sumsub-token-abc"
        assert resp.kyc_status == "pending"

        await client.close()

    async def test_start_404_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient(hl_wallet=VALID_ADDRESS)
        await client.open()

        client.http.post = AsyncMock(return_value=_make_error_response(404, "POST"))

        with pytest.raises(HyperscaledError, match="KYC request failed"):
            await client.kyc.start_async()

        await client.close()

    async def test_start_500_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
        client = HyperscaledClient(hl_wallet=VALID_ADDRESS)
        await client.open()

        client.http.post = AsyncMock(return_value=_make_error_response(500, "POST"))

        with pytest.raises(HyperscaledError, match="Failed to start KYC"):
            await client.kyc.start_async()

        await client.close()


# ── CLI: hyperscaled kyc status ──────────────────────────


class TestKycStatusCLI:
    def test_status_render(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        info = KycInfo(
            wallet=VALID_ADDRESS,
            kyc_status="approved",
            verified=True,
            verified_at="2026-03-15T10:00:00Z",
        )
        with patch("hyperscaled.sdk.kyc.KYCClient.status", return_value=info):
            result = runner.invoke(app, ["kyc", "status"])

        assert result.exit_code == 0
        assert VALID_ADDRESS in result.output
        assert "approved" in result.output
        assert "Yes" in result.output

    def test_status_json(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        info = KycInfo(
            wallet=VALID_ADDRESS,
            kyc_status="pending",
            verified=False,
        )
        with patch("hyperscaled.sdk.kyc.KYCClient.status", return_value=info):
            result = runner.invoke(app, ["kyc", "status", "--json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["kyc_status"] == "pending"
        assert data["verified"] is False

    def test_status_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        with patch(
            "hyperscaled.sdk.kyc.KYCClient.status",
            side_effect=HyperscaledError("No Hyperliquid wallet configured."),
        ):
            result = runner.invoke(app, ["kyc", "status"])

        assert result.exit_code == 1
        assert "No Hyperliquid wallet configured" in result.output


# ── CLI: hyperscaled kyc start ──────────────────────────


class TestKycStartCLI:
    def test_start_success(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        info = KycInfo(wallet=VALID_ADDRESS, kyc_status="none", verified=False)
        token_resp = KycTokenResponse(token="tok-123", kyc_status="pending")

        with (
            patch("hyperscaled.sdk.kyc.KYCClient.status", return_value=info),
            patch("hyperscaled.sdk.kyc.KYCClient.start", return_value=token_resp),
            patch("hyperscaled.cli.kyc.webbrowser.open") as mock_open,
        ):
            result = runner.invoke(app, ["kyc", "start"])

        assert result.exit_code == 0
        assert "KYC verification started" in result.output
        mock_open.assert_called_once()

    def test_start_already_approved(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        info = KycInfo(
            wallet=VALID_ADDRESS,
            kyc_status="approved",
            verified=True,
            verified_at="2026-03-15T10:00:00Z",
        )
        with patch("hyperscaled.sdk.kyc.KYCClient.status", return_value=info):
            result = runner.invoke(app, ["kyc", "start"])

        assert result.exit_code == 0
        assert "already approved" in result.output

    def test_start_no_browser(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        info = KycInfo(wallet=VALID_ADDRESS, kyc_status="none", verified=False)
        token_resp = KycTokenResponse(token="tok-123", kyc_status="pending")

        with (
            patch("hyperscaled.sdk.kyc.KYCClient.status", return_value=info),
            patch("hyperscaled.sdk.kyc.KYCClient.start", return_value=token_resp),
            patch("hyperscaled.cli.kyc.webbrowser.open") as mock_open,
        ):
            result = runner.invoke(app, ["kyc", "start", "--no-browser"])

        assert result.exit_code == 0
        assert "KYC verification started" in result.output
        mock_open.assert_not_called()

    def test_start_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")

        with patch(
            "hyperscaled.sdk.kyc.KYCClient.status",
            side_effect=HyperscaledError("Wallet not found. Register first."),
        ):
            result = runner.invoke(app, ["kyc", "start"])

        assert result.exit_code == 1
        assert "Register first" in result.output
