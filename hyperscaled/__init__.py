"""Hyperscaled — CLI & SDK for the Hyperscaled funded trading platform on Hyperliquid."""

from importlib.metadata import version

__version__ = version("hyperscaled")

from hyperscaled.sdk.client import HyperscaledClient

__all__ = ["HyperscaledClient", "__version__"]
