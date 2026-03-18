# Hyperscaled CLI & SDK — Sprint 3 Tickets

Sprint 3 is the third of three sprints in Phase 1. See [V2_Hyperscaled CLI & SDK Design.md](../V2_Hyperscaled%20CLI%20%26%20SDK%20Design.md) for the updated design reference and [OVERVIEW.md](../OVERVIEW.md) for how the existing repos fit together.

---

## Phase Overview

### Phase 1 — Funded Account Registration and Trading (Sprints 04–06)

Everything a trader or agent needs end-to-end: signup, funded account purchase, Hyperliquid wallet setup, registration status tracking, trading, and account monitoring. Consumes backend APIs from ENG-B-002 through ENG-B-016 and direct Hyperliquid SDK integrations where needed.

**Target:** Complete by end of Sprint 2026.06 (04/07)

| Sprint | Dates | Backend APIs Available | CLI/SDK Focus |
|--------|-------|------------------------|---------------|
| 2026.04 | 02/24 – 03/10 | ENG-B-002 (miner config), ENG-B-008/009 (validator endpoints) | Package foundation, config, core client, miner discovery |
| 2026.05 | 03/11 – 03/24 | ENG-B-003 (x402), ENG-B-004 (wallet capture), ENG-B-005 (registration pipeline), ENG-B-006 (status polling) | Wallet validation, HL account setup, balance checks, purchase & registration flow |
| **2026.06** | **03/25 – 04/07** | **ENG-B-008/009 (validator endpoints), Vanta Network rules API, Hyperliquid SDK (direct)** | **Trade submission, cancellation, local rule enforcement, open positions & orders** |

### Phase 2 — Data and Backtesting (Sprints 07–12)

Data providers, local backtesting, and the research-to-live workflow described in the V2 design.

**Target:** Complete by end of Sprint 2026.12 (06/30)

---

## Sprint 2026.06 (03/25 – 04/07) — Trading Execution + Portfolio Visibility

**Goal:** Turn the SDK and CLI from registration-only flows into usable funded-trading tooling: submit and cancel Hyperliquid orders, enforce Vanta constraints before the order hits the wire, and expose open positions and open orders for monitoring and automation.

This sprint builds directly on the wallet, balance, and funded-account setup completed in Sprint 2. The main work is wiring direct Hyperliquid execution together with Vanta-owned rule checks and validator reads so users can trade safely while still seeing the translated funded-account view.

---

### SDK-010 — Trade submission (SDK + CLI)

Expose the first live trade path in the SDK and CLI. A submitted Hyperliquid order should return the execution identifier plus the funded-account translated sizing fields that agents and downstream monitoring flows need.

**SDK interface (`sdk/trading.py`):**

```python
class TradingClient:
    async def submit(
        self,
        pair: str,
        side: Literal["long", "short"],
        size: Decimal,
        order_type: Literal["market", "limit"],
        take_profit: Decimal | None = None,
        stop_loss: Decimal | None = None,
        price: Decimal | None = None,
    ) -> Order:
        """Submit an order and return translated funded-account execution info."""
```

**Expected result shape:**

```python
{
    "hl_order_id": "0xabc123",
    "funded_equivalent_size": Decimal("20000"),
    "status": "filled",
    "fill_price": Decimal("100250.50"),
    "scaling_ratio": Decimal("100.0"),
}
```

**CLI command (`cli/trade.py`):**

```bash
hyperscaled trade submit --pair BTC-USDC --side long --size 200 --type market
hyperscaled trade submit --pair ETH-USDC --side short --size 100 --type limit --price 3500
```

**Behavior notes:**
- `limit` orders require `price`; `market` orders must ignore or reject it explicitly
- `take_profit` and `stop_loss` are optional, but should be passed through consistently in the returned `Order`
- `funded_equivalent_size` must be derived from the documented ratio `funded_account_size / hl_account_balance`
- `scaling_ratio` should be returned explicitly so scripts can reconcile Hyperliquid notional against funded-account notional
- Partial fills are first-class and must be preserved as structured order states rather than collapsed into a simple success/failure result
- `client.trade.submit()` must run the SDK-012 validation layer before any direct Hyperliquid submission attempt

**Acceptance criteria:**
- `client.trade.submit(...)` places market and limit orders through the direct Hyperliquid integration
- Successful submissions return `hl_order_id`, `funded_equivalent_size`, `status`, `fill_price`, and `scaling_ratio`
- Partial fills are surfaced as structured order states and covered by tests
- `hyperscaled trade submit` supports both human-readable output and clean error handling
- Limit orders fail fast if `price` is missing; market orders fail fast if an invalid price combination is passed
- Mock-based tests cover filled, partial, pending, rejected, and Hyperliquid transport failure paths

| | |
|---|---|
| **Label** | Feature |
| **Priority** | High |
| **Depends on** | SDK-007, SDK-008 |
| **Backend dependency** | Hyperliquid SDK (direct), Vanta Network rules API |
| **Estimate** | 1.5 days |

---

### SDK-011 — Trade cancellation (SDK + CLI)

Expose order cancellation for both one-off manual recovery and scripted safety controls. This should sit on the same trade client as submission so open-order lifecycle management stays in one place.

**SDK interface (`sdk/trading.py`):**

```python
class TradingClient:
    async def cancel(self, order_id: str) -> dict[str, object]:
        """Cancel a single open order by Hyperliquid order ID."""

    async def cancel_all(self) -> dict[str, object]:
        """Cancel all cancellable open orders for the configured account."""
```

**CLI commands (`cli/trade.py`):**

```bash
hyperscaled trade cancel <order_id>
hyperscaled trade cancel-all
```

**Behavior notes:**
- `cancel(order_id)` should target the `hl_order_id` returned by `client.trade.submit()`
- `cancel_all()` should only attempt to cancel currently open/cancellable orders
- Already-filled, already-cancelled, or unknown order IDs should surface a clear structured result instead of ambiguous success text
- CLI output should make it obvious whether zero, one, or many orders were actually cancelled

**Acceptance criteria:**
- `client.trade.cancel(order_id)` cancels a single open order and returns structured status data
- `client.trade.cancel_all()` cancels all currently open orders for the configured account
- `hyperscaled trade cancel` and `hyperscaled trade cancel-all` report success/failure clearly
- Cancellation of unknown or already-closed orders is handled gracefully
- Mock-based tests cover single cancel success, cancel-all success, no open orders, unknown order ID, and Hyperliquid API failure handling

| | |
|---|---|
| **Label** | Feature |
| **Priority** | High |
| **Depends on** | SDK-010 |
| **Backend dependency** | Hyperliquid SDK (direct) |
| **Estimate** | 0.5 day |

---

### SDK-012 — Pre-submission local rule enforcement

Validate each proposed trade locally before any order is sent to Hyperliquid. This ticket turns the Vanta rule model into an actual preflight gate for SDK and CLI users, with typed exceptions that are useful in scripts as well as interactive CLI sessions.

**SDK interface (`sdk/rules.py`):**

```python
class RulesClient:
    async def validate_trade(
        self,
        pair: str,
        side: Literal["long", "short"],
        size: Decimal,
        order_type: Literal["market", "limit"],
        price: Decimal | None = None,
    ) -> TradeValidation:
        """Validate a proposed trade locally before submission."""
```

`client.trade.submit()` should call this automatically before placing any order, so CLI users get the same enforcement without a separate manual validation step.

**CLI wiring:**

```bash
hyperscaled trade submit --pair BTC-USDC --side long --size 200 --type market --strict
```

**Validation rules:**
- Pair is supported on Vanta Network -> `UnsupportedPairError`
- Leverage is within account-level and position-level limits -> `LeverageLimitError`
- Hyperliquid balance is at least `$1,000` -> `InsufficientBalanceError`
- Funded account notional exposure limit is not exceeded -> `ExposureLimitError`

**Error contract:**
- Every rule error must expose `rule_id`, `current_value`, `limit`, and `message`
- CLI `--strict` mode should exit with code `1` for rule violations so shell pipelines can treat validation failure as a hard stop
- Human-readable CLI output should still explain the failing rule when `--strict` is not used

**Acceptance criteria:**
- `client.rules.validate_trade(...)` returns a structured `TradeValidation` result for valid trades
- `client.trade.submit(...)` blocks invalid submissions before any Hyperliquid call is made
- Unsupported pair, leverage, balance, and exposure violations raise the correct typed error
- Each raised error includes `rule_id`, `current_value`, `limit`, and `message`
- CLI `--strict` mode exits with code `1` on local rule violations
- Mock-based tests cover each rule failure branch plus the successful validation path

| | |
|---|---|
| **Label** | Feature |
| **Priority** | High |
| **Depends on** | SDK-010, SDK-015 |
| **Backend dependency** | Vanta Network rules API |
| **Estimate** | 1 day |

> **🔄 Sync required:** Confirm the rules API contract before implementation starts. Specifically align on supported-pair source of truth, leverage-limit field names, exposure-limit calculation inputs, and the exact `rule_id` values/messages that should appear in SDK exceptions and CLI output.

---

### SDK-013 — Open positions & orders (SDK + CLI)

Expose read-only portfolio visibility for open positions and open orders so traders and agents can inspect live account state without needing the browser extension or direct validator calls.

**SDK interface (`sdk/portfolio.py`):**

```python
class PortfolioClient:
    async def open_positions(self) -> list[Position]:
        """Return currently open positions for the configured funded account."""

    async def open_orders(self) -> list[Order]:
        """Return currently open orders for the configured funded account."""
```

**CLI commands (`cli/positions.py`):**

```bash
hyperscaled positions open
hyperscaled positions open --json
hyperscaled orders open
```

**Behavior notes:**
- Reads are permissionless and should use the validator endpoints from ENG-B-008/009
- `open_positions()` should return `symbol`, `side`, `size`, `position_value`, `entry_price`, `mark_price`, `liquidation_price`, `unrealized_pnl`, `take_profit`, `stop_loss`, and `open_time`
- `open_orders()` should return the current open-order view only; historical order/position queries are out of scope for this ticket
- The default lookup should use the locally configured `funded_account_id` saved during the registration flow
- CLI `--json` output should serialize cleanly from the shared Pydantic models for agent use

**Acceptance criteria:**
- `client.portfolio.open_positions()` returns `List[Position]` from validator data
- `client.portfolio.open_orders()` returns `List[Order]` from validator data
- `hyperscaled positions open` shows a readable table of live positions
- `hyperscaled positions open --json` and `hyperscaled orders open` produce reliable structured output
- Missing or unknown funded account identifiers are handled cleanly
- Mock-based tests cover empty positions, empty orders, populated responses, and validator API failure handling

| | |
|---|---|
| **Label** | Feature |
| **Priority** | High |
| **Depends on** | SDK-003 |
| **Backend dependency** | ENG-B-008/009 |
| **Estimate** | 1 day |

---

## Sprint 3 Summary

| Ticket | Title | Depends on | Priority | Estimate |
|--------|-------|------------|----------|----------|
| SDK-010 | Trade submission (SDK + CLI) | SDK-007, SDK-008 | High | 1.5 days |
| SDK-011 | Trade cancellation (SDK + CLI) | SDK-010 | High | 0.5 day |
| SDK-012 | Pre-submission local rule enforcement | SDK-010, SDK-015 | High | 1 day |
| SDK-013 | Open positions & orders (SDK + CLI) | SDK-003 | High | 1 day |

**Total estimate:** 4 days

**Parallelism:** `SDK-013` can start immediately on top of the existing client and model foundation. `SDK-010` can proceed in parallel with validator-read work once the Sprint 2 account setup flow is stable. `SDK-011` follows naturally after submission exists. `SDK-012` depends on both trade submission wiring and the shared rules contract from `SDK-015`, but mocks and exception-shape work can begin before the final rules API contract is live.

```text
SDK-010 ── SDK-011
    └──── SDK-012

SDK-015 ── SDK-012

SDK-013
```

**Sprint 06 exit criteria:**
- `hyperscaled trade submit` can place market and limit orders and returns funded-account translated sizing data
- Invalid trades are blocked locally before submission with typed rule-violation errors
- `hyperscaled trade cancel` and `hyperscaled trade cancel-all` manage open orders cleanly
- `hyperscaled positions open` and `hyperscaled orders open` return live validator-backed views
- CLI output supports both human-readable usage and automation-oriented `--json` / `--strict` flows
- CI green: lint, type-check, and tests passing for all new trading and portfolio flows

---

## What's Next

> **🔄 Phase 2 prep:** Once Sprint 2026.06 lands, align live-trading order/position vocabulary across Hyperliquid responses, validator portfolio reads, and future backtesting models so the research-to-live workflow can reuse one consistent set of SDK types.

**Phase 2 begins next with the data and backtesting layer:**

- Market/data access for research workflows
- Local backtesting primitives and result models
- Research-to-live continuity for agents and scripts
