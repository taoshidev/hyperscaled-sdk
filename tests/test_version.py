"""Tests for version resolution in installed and local-checkout contexts."""

from importlib.metadata import PackageNotFoundError

import pytest

from hyperscaled._version import get_version


def test_get_version_from_installed_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("hyperscaled._version.version", lambda _: "1.2.3")
    assert get_version() == "1.2.3"


def test_get_version_falls_back_when_metadata_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def _missing(_: str) -> str:
        raise PackageNotFoundError("hyperscaled")

    monkeypatch.setattr("hyperscaled._version.version", _missing)
    assert get_version() == "0.0.0+local"
