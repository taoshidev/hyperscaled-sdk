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

    payouts = _SubClientDescriptor("PayoutsClient", "Sprint 06")
    kyc = _SubClientDescriptor("KYCClient", "Sprint 06")
    data = _SubClientDescriptor("DataClient", "Phase 2")
    backtest = _SubClientDescriptor("BacktestClient", "Phase 2")

    def __init__(
        self,
        *,
        hl_wallet: str | None = None,
        payout_wallet: str | None = None,
        base_url: str | None = None,
        hl_private_key: str | None = None,
    ) -> None:
        self._config = Config.load()

        if hl_wallet is not None:
            self._config.set_value("wallet.hl_address", hl_wallet)
        if payout_wallet is not None:
            self._config.set_value("wallet.payout_address", payout_wallet)
        if base_url is not None:
            self._config.set_value("api.hyperscaled_base_url", base_url)

        self._hl_private_key = hl_private_key
        self._http: httpx.AsyncClient | None = None
        self._owns_http = True

    @property
    def config(self) -> Config:
        """The resolved configuration for this client."""
        return self._config

    @property
    def http(self) -> httpx.AsyncClient:
        """The shared ``httpx.AsyncClient`` session.

        Created lazily on first access.  Use :meth:`open` / :meth:`close` or
        the async context manager to control the lifecycle explicitly.
        """
        if self._http is None or self._http.is_closed:
            self._http = self._build_http_client()
            self._owns_http = True
        return self._http

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

    def _resolve_hl_private_key(self) -> str:
        """Return the HL private key from constructor param or environment."""
        resolved = self._hl_private_key or os.environ.get("HYPERSCALED_HL_PRIVATE_KEY", "")
        if not resolved:
            raise HyperscaledError(
                "No Hyperliquid private key provided. "
                "Pass hl_private_key= to HyperscaledClient() or set HYPERSCALED_HL_PRIVATE_KEY."
            )
        return resolved

    def _build_http_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._config.api.hyperscaled_base_url,
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

    def open_sync(self) -> HyperscaledClient:
        """Synchronous version of :meth:`open`."""
        result: HyperscaledClient = _run_sync(self.open())
        return result

    def close_sync(self) -> None:
        """Synchronous version of :meth:`close`."""
        _run_sync(self.close())

    async def __aenter__(self) -> HyperscaledClient:
        return await self.open()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.close()
