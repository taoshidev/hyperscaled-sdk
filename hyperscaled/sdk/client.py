"""HyperscaledClient — main entry point for programmatic SDK use."""

from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING, Any, TypeVar

import httpx

from hyperscaled.exceptions import HyperscaledError
from hyperscaled.sdk.config import Config

if TYPE_CHECKING:
    from types import TracebackType

_DEFAULT_TIMEOUT = 30.0
_DEFAULT_HEADERS = {"User-Agent": "hyperscaled-sdk"}

T = TypeVar("T")


def _run_sync(coro: Any) -> Any:
    """Run an async coroutine from synchronous code.

    Uses ``asyncio.run()`` when no event loop is running.  When called from
    inside an already-running loop (e.g. Jupyter) the caller should ``await``
    the coroutine directly instead.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        raise RuntimeError(
            "HyperscaledClient sync helpers cannot be used inside a running event loop. "
            "Use 'await' directly or run in a separate thread."
        )
    return asyncio.run(coro)


class _SubClientDescriptor:
    """Descriptor that raises ``NotImplementedError`` for sub-clients not yet wired."""

    def __init__(self, name: str, target: str) -> None:
        self._name = name
        self._target = target

    def __set_name__(self, owner: type, name: str) -> None:
        self._attr = f"_{name}"

    def __get__(self, obj: Any, objtype: type | None = None) -> Any:
        if obj is None:
            return self
        cached = getattr(obj, self._attr, None)
        if cached is not None:
            return cached
        raise NotImplementedError(f"{self._name} is not yet implemented — target: {self._target}")

    def __set__(self, obj: Any, value: Any) -> None:
        setattr(obj, self._attr, value)


class HyperscaledClient:
    """Main client for the Hyperscaled SDK.

    Loads config from ``~/.hyperscaled/config.toml``, manages a shared
    ``httpx.AsyncClient`` session, and lazy-loads sub-clients on first access.

    Supports both async and sync usage::

        # Async
        async with HyperscaledClient() as client:
            miners = await client.miners.list_all()

        # Sync (outside an event loop)
        client = HyperscaledClient()
        client.open_sync()
        ...
        client.close_sync()

    Constructor overrides take precedence over config file values, which take
    precedence over environment variables.
    """

    data = _SubClientDescriptor("DataClient", "Phase 2")
    backtest = _SubClientDescriptor("BacktestClient", "Phase 2")

    def __init__(
        self,
        *,
        hl_wallet: str | None = None,
        payout_wallet: str | None = None,
        base_url: str | None = None,
        validator_api_url: str | None = None,
        hl_private_key: str | None = None,
    ) -> None:
        self._config = Config.load()

        if hl_wallet is not None:
            self._config.set_value("wallet.hl_address", hl_wallet)
        if payout_wallet is not None:
            self._config.set_value("wallet.payout_address", payout_wallet)
        if base_url is not None:
            self._config.set_value("api.hyperscaled_base_url", base_url)
        if validator_api_url is not None:
            self._config.set_value("api.validator_api_url", validator_api_url)

        self._hl_private_key = hl_private_key
        self._http: httpx.AsyncClient | None = None
        self._owns_http = True
        self._validator_http: httpx.AsyncClient | None = None
        self._owns_validator_http = True

    @property
    def config(self) -> Config:
        """The resolved configuration for this client."""
        return self._config

    def __setattr__(self, name: str, value: Any) -> None:
        super().__setattr__(name, value)
        if name in ("_http", "_validator_http"):
            # Record which event loop owns this http client so we can detect
            # loop changes and avoid reusing a transport across asyncio.run() calls.
            try:
                loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            loop_attr = "_http_loop" if name == "_http" else "_validator_http_loop"
            super().__setattr__(loop_attr, loop)

    @property
    def http(self) -> httpx.AsyncClient:
        """The shared ``httpx.AsyncClient`` session.

        Created lazily on first access.  Use :meth:`open` / :meth:`close` or
        the async context manager to control the lifecycle explicitly.
        """
        try:
            running_loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        # If we're in a different event loop than the one that created the http
        # client, the underlying anyio transport references a closed loop and
        # will raise "RuntimeError: Event loop is closed" on the next request.
        # Create a fresh client for the new loop instead.
        #
        # Only treat as stale when _http_loop is a *real* (non-None) loop that
        # differs from the current one.  When _http_loop is None the client was
        # injected from sync context (e.g. tests) and is safe to reuse.
        _http_loop = getattr(self, "_http_loop", None)
        loop_stale = (
            running_loop is not None
            and _http_loop is not None
            and running_loop is not _http_loop
        )

        if self._http is None or self._http.is_closed or loop_stale:
            self._http = self._build_http_client(self._config.api.hyperscaled_base_url)
            self._owns_http = True
        return self._http

    @property
    def validator_http(self) -> httpx.AsyncClient:
        """HTTP session for the Hyperscaled validator / orchestrator API."""
        try:
            running_loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        _vh_loop = getattr(self, "_validator_http_loop", None)
        loop_stale = (
            running_loop is not None
            and _vh_loop is not None
            and running_loop is not _vh_loop
        )

        if self._validator_http is None or self._validator_http.is_closed or loop_stale:
            self._validator_http = self._build_http_client(self._config.api.validator_api_url)
            self._owns_validator_http = True
        return self._validator_http

    @property
    def miners(self) -> Any:
        """The lazy-loaded entity miner client."""
        cached = getattr(self, "_miners", None)
        if cached is None:
            from hyperscaled.sdk.miners import MinersClient

            cached = MinersClient(self)
            self._miners = cached
        return cached

    @miners.setter
    def miners(self, value: Any) -> None:
        self._miners = value

    @property
    def account(self) -> Any:
        """The lazy-loaded account client."""
        cached = getattr(self, "_account", None)
        if cached is None:
            from hyperscaled.sdk.account import AccountClient

            cached = AccountClient(self)
            self._account = cached
        return cached

    @account.setter
    def account(self, value: Any) -> None:
        self._account = value

    @property
    def register(self) -> Any:
        """The lazy-loaded registration client."""
        cached = getattr(self, "_register", None)
        if cached is None:
            from hyperscaled.sdk.register import RegisterClient

            cached = RegisterClient(self)
            self._register = cached
        return cached

    @register.setter
    def register(self, value: Any) -> None:
        self._register = value

    @property
    def trade(self) -> Any:
        """The lazy-loaded trading client."""
        cached = getattr(self, "_trade", None)
        if cached is None:
            from hyperscaled.sdk.trading import TradingClient

            cached = TradingClient(self)
            self._trade = cached
        return cached

    @trade.setter
    def trade(self, value: Any) -> None:
        self._trade = value

    @property
    def rules(self) -> Any:
        """The lazy-loaded rules client."""
        cached = getattr(self, "_rules", None)
        if cached is None:
            from hyperscaled.sdk.rules import RulesClient

            cached = RulesClient(self)
            self._rules = cached
        return cached

    @rules.setter
    def rules(self, value: Any) -> None:
        self._rules = value

    @property
    def portfolio(self) -> Any:
        """The lazy-loaded portfolio client."""
        cached = getattr(self, "_portfolio", None)
        if cached is None:
            from hyperscaled.sdk.portfolio import PortfolioClient

            cached = PortfolioClient(self)
            self._portfolio = cached
        return cached

    @portfolio.setter
    def portfolio(self, value: Any) -> None:
        self._portfolio = value

    @property
    def payouts(self) -> Any:
        """The lazy-loaded payouts client."""
        cached = getattr(self, "_payouts", None)
        if cached is None:
            from hyperscaled.sdk.payouts import PayoutsClient

            cached = PayoutsClient(self)
            self._payouts = cached
        return cached

    @payouts.setter
    def payouts(self, value: Any) -> None:
        self._payouts = value

    @property
    def kyc(self) -> Any:
        """The lazy-loaded KYC client."""
        cached = getattr(self, "_kyc", None)
        if cached is None:
            from hyperscaled.sdk.kyc import KYCClient

            cached = KYCClient(self)
            self._kyc = cached
        return cached

    @kyc.setter
    def kyc(self, value: Any) -> None:
        self._kyc = value

    def _resolve_hl_private_key(self) -> str:
        """Return the HL private key from constructor param or environment."""
        resolved = self._hl_private_key or os.environ.get("HYPERSCALED_HL_PRIVATE_KEY", "")
        if not resolved:
            raise HyperscaledError(
                "No Hyperliquid private key provided. "
                "Pass hl_private_key= to HyperscaledClient() or set HYPERSCALED_HL_PRIVATE_KEY."
            )
        return resolved

    def resolve_hl_wallet_address(self) -> str:
        """Return the Hyperliquid address for validator dashboard and HL API calls.

        Uses ``wallet.hl_address`` when set; otherwise derives the address from the
        configured private key so trading works with only ``HYPERSCALED_HL_PRIVATE_KEY``.
        """
        addr = (self._config.wallet.hl_address or "").strip()
        if addr:
            return addr
        raw_key = self._hl_private_key or os.environ.get("HYPERSCALED_HL_PRIVATE_KEY", "")
        if not raw_key:
            raise HyperscaledError(
                "No Hyperliquid wallet configured. "
                "Set HYPERSCALED_HL_ADDRESS, run `hyperscaled account setup <wallet>`, "
                "or set HYPERSCALED_HL_PRIVATE_KEY so the address can be derived."
            )
        try:
            from eth_account import Account
        except ImportError as exc:
            raise HyperscaledError(
                "Cannot derive wallet address: eth_account is not installed."
            ) from exc
        try:
            derived: str = str(Account.from_key(raw_key).address)
            return derived
        except Exception as exc:
            raise HyperscaledError(
                f"Could not derive wallet from private key: {type(exc).__name__}"
            ) from exc

    def _build_http_client(self, base_url: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=base_url,
            headers=_DEFAULT_HEADERS,
            timeout=_DEFAULT_TIMEOUT,
        )

    # ── Lifecycle ────────────────────────────────────────────

    async def open(self) -> HyperscaledClient:
        """Ensure the HTTP session is open.  Returns ``self`` for chaining."""
        _ = self.http  # triggers lazy creation
        return self

    async def close(self) -> None:
        """Close the HTTP session if this client owns it."""
        if self._http is not None and self._owns_http and not self._http.is_closed:
            await self._http.aclose()
        if (
            self._validator_http is not None
            and self._owns_validator_http
            and not self._validator_http.is_closed
        ):
            await self._validator_http.aclose()

    def open_sync(self) -> HyperscaledClient:
        """Synchronous version of :meth:`open`."""
        result: HyperscaledClient = _run_sync(self.open())
        return result

    def close_sync(self) -> None:
        """Synchronous version of :meth:`close`."""
        try:
            _run_sync(self.close())
        except RuntimeError as exc:
            # httpx/anyio may schedule transport cleanup after asyncio.run() begins
            # tearing down the loop (e.g. when Typer runs finally: after typer.Exit).
            if "Event loop is closed" not in str(exc):
                raise

    async def __aenter__(self) -> HyperscaledClient:
        return await self.open()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.close()
