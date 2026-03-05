"""Version helpers for installed and local-checkout usage."""

from importlib.metadata import PackageNotFoundError, version


def get_version() -> str:
    """Return the installed package version, or a local fallback."""
    try:
        return version("hyperscaled")
    except PackageNotFoundError:
        return "0.0.0+local"
