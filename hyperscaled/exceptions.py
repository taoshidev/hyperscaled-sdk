"""Exception hierarchy for Hyperscaled SDK.

Wired in SDK-004 — stubs defined here for clean imports.
"""


class HyperscaledError(Exception):
    """Base exception for all Hyperscaled errors."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)
