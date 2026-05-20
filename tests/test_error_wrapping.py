"""Cross-file integration tests for the new error-wrapping contract.

Verifies that every swept call site produces a :class:`HyperscaledError` (or
subclass) with stable ``code`` and ``retryable`` fields, regardless of which
upstream error shape is raised. Partners reading errors programmatically can
rely on this contract.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from hyperscaled.exceptions import (
    HyperscaledClientError,
    HyperscaledError,
    HyperscaledServerError,
)
from hyperscaled.sdk.client import HyperscaledClient

VALID_ADDRESS = "0x" + "a1" * 20


def _resp(status: int, text: str = "boom") -> httpx.Response:
    return httpx.Response(
        status,
        text=text,
        request=httpx.Request("POST", "https://example.com"),
    )


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> HyperscaledClient:
    monkeypatch.setattr("hyperscaled.sdk.config._DEFAULT_PATH", tmp_path / "config.toml")
    return HyperscaledClient(hl_wallet=VALID_ADDRESS)


# Each parametrize entry: (label, mock_kwargs, expected_subclass, expected_code, expected_retryable)
_FAILURE_MODES = [
    (
        "404",
        {"return_value": _resp(404, "not found")},
        HyperscaledClientError,
        "HS_API_404",
        False,
    ),
    (
        "500",
        {"return_value": _resp(500, "server error")},
        HyperscaledServerError,
        "HS_API_500",
        True,
    ),
    (
        "502",
        {"return_value": _resp(502, "bad gateway")},
        HyperscaledServerError,
        "HS_API_502",
        True,
    ),
    (
        "timeout",
        {"side_effect": httpx.ReadTimeout("read timeout", request=httpx.Request("GET", "/x"))},
        HyperscaledServerError,
        "HS_NETWORK_TIMEOUT",
        True,
    ),
    (
        "connect_error",
        {"side_effect": httpx.ConnectError("conn refused", request=httpx.Request("GET", "/x"))},
        HyperscaledServerError,
        "HS_NETWORK_ERROR",
        True,
    ),
]


@pytest.mark.parametrize(
    "label,mock_kwargs,expected_cls,expected_code,expected_retryable", _FAILURE_MODES
)
class TestAccountBalanceErrors:
    """``check_balance_async`` must never silently return zero on HL errors."""

    async def test_check_balance_native_failure(
        self,
        label: str,  # noqa: ARG002
        mock_kwargs: dict,
        expected_cls: type,
        expected_code: str,
        expected_retryable: bool,
        client: HyperscaledClient,
    ) -> None:
        await client.open()
        # First .post() is _fetch_perps_equity for the native dex; that's the one we test.
        client.http.post = AsyncMock(**mock_kwargs)  # type: ignore[method-assign]
        with pytest.raises(HyperscaledError) as excinfo:
            await client.account.check_balance_async()
        assert isinstance(excinfo.value, expected_cls)
        assert excinfo.value.code == expected_code
        assert excinfo.value.retryable is expected_retryable
        await client.close()


@pytest.mark.parametrize(
    "label,mock_kwargs,expected_cls,expected_code,expected_retryable", _FAILURE_MODES
)
class TestRulesDashboardErrors:
    """``_fetch_dashboard`` wraps validator failures with structured fields."""

    async def test_dashboard_failure(
        self,
        label: str,
        mock_kwargs: dict,
        expected_cls: type,
        expected_code: str,
        expected_retryable: bool,
        client: HyperscaledClient,
    ) -> None:
        # 404 is special-cased into a friendly domain-specific message
        # (HS_DASHBOARD_NOT_FOUND) so a caller can give helpful guidance.
        if label == "404":
            pytest.skip(
                "dashboard 404 produces a domain-specific message, not the generic wrapper"
            )
        await client.open()
        client.validator_http.get = AsyncMock(**mock_kwargs)  # type: ignore[method-assign]
        with pytest.raises(HyperscaledError) as excinfo:
            await client.rules._fetch_dashboard(VALID_ADDRESS)
        assert isinstance(excinfo.value, expected_cls)
        assert excinfo.value.code == expected_code
        assert excinfo.value.retryable is expected_retryable
        await client.close()


@pytest.mark.parametrize(
    "label,mock_kwargs,expected_cls,expected_code,expected_retryable", _FAILURE_MODES
)
class TestKycErrors:
    async def test_kyc_status_failure(
        self,
        label: str,
        mock_kwargs: dict,
        expected_cls: type,
        expected_code: str,
        expected_retryable: bool,
        client: HyperscaledClient,
    ) -> None:
        # 404 is special-cased in kyc.status_async — it raises a friendly
        # message instead of routing through from_http.
        if label == "404":
            pytest.skip("kyc 404 produces a domain-specific message, not the generic wrapper")
        await client.open()
        client.http.get = AsyncMock(**mock_kwargs)  # type: ignore[method-assign]
        with pytest.raises(HyperscaledError) as excinfo:
            await client.kyc.status_async()
        assert isinstance(excinfo.value, expected_cls)
        assert excinfo.value.code == expected_code
        assert excinfo.value.retryable is expected_retryable
        await client.close()


class TestBadJsonWrapping:
    """Malformed JSON bodies are wrapped, not bubbled as JSONDecodeError."""

    async def test_dashboard_bad_json(self, client: HyperscaledClient) -> None:
        await client.open()
        client.validator_http.get = AsyncMock(  # type: ignore[method-assign]
            return_value=_resp(200, text="<<not json>>")
        )
        with pytest.raises(HyperscaledError) as excinfo:
            await client.rules._fetch_dashboard(VALID_ADDRESS)
        assert excinfo.value.code == "HS_BAD_JSON"
        assert excinfo.value.retryable is False
        assert excinfo.value.body_excerpt == "<<not json>>"
        await client.close()


class TestRetryableContract:
    """Callers should be able to build retry middleware from .retryable alone."""

    def test_4xx_errors_are_not_retryable(self) -> None:
        for status in (400, 401, 403, 404, 422, 429):
            response = httpx.Response(status, text="x")
            exc = httpx.HTTPStatusError(
                "x", request=httpx.Request("GET", "/x"), response=response
            )
            wrapped = HyperscaledError.from_http(exc, operation="x")
            assert wrapped.retryable is False, f"{status} should not be retryable"

    def test_5xx_and_network_errors_are_retryable(self) -> None:
        for status in (500, 502, 503, 504):
            response = httpx.Response(status, text="x")
            exc = httpx.HTTPStatusError(
                "x", request=httpx.Request("GET", "/x"), response=response
            )
            wrapped = HyperscaledError.from_http(exc, operation="x")
            assert wrapped.retryable is True, f"{status} should be retryable"
