"""Hyperscaled — CLI & SDK for the Hyperscaled funded trading platform on Hyperliquid."""

from hyperscaled._version import get_version

__version__ = get_version()

from hyperscaled.sdk.client import HyperscaledClient

__all__ = ["HyperscaledClient", "__version__"]
