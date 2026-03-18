# Hyperscaled CLI & SDK Design

This document describes `hyperscaled-cli` and the `hyperscaled` PyPI package — a programmatic interface to the full Hyperscaled ecosystem for developers, agents, and builders.

See [OVERVIEW.md](./OVERVIEW.md) for how the existing repos fit together.

---

## 1. What This Is

A Python CLI and SDK that exposes the entire Hyperscaled funded-trading lifecycle as code:

1. **Data** — Access market data from private and OSS providers
2. **Backtest** — Test strategies using QuantConnect Lean with Vanta Network rules applied
3. **Account** — Set up and fund a Hyperliquid account programmatically
4. **Miners** — Browse entity miners and their pricing/configuration
5. **Register** — Purchase a funded account and connect it to a Hyperliquid wallet
6. **Trade** — Submit trades on Hyperliquid that map to funded-account positions under Vanta Network rules
7. **Portfolio** — Monitor positions, orders, account info, and payout history
8. **KYC** — Complete identity verification (gates payouts, not trading)
9. **Rules** — Query and validate against all Vanta Network rules

### Where this fits in the ecosystem

```
                    ┌──────────────────────────────────────────┐
                    │           USER / AGENT INTERFACES         │
                    │                                          │
  Existing:         │  Landing Page    Chrome Extension        │
  (hyperscaled/,    │  (Next.js)       (MV3, injects into HL) │
   hyperscaled_     │                                          │
   extension/)      ├──────────────────────────────────────────┤
                    │                                          │
  New:              │  hyperscaled CLI & SDK  ◀── this doc     │
  (hyperscaled      │  (PyPI package)                          │
   PyPI pkg)        │                                          │
                    └────────┬─────────────────┬───────────────┘
                             │                 │
                    ┌────────▼──────┐  ┌───────▼────────┐
                    │ Vanta Network │  │  Hyperliquid   │
                    │ (Bittensor    │  │  (exchange)    │
                    │  subnet)      │  │                │
                    └───────────────┘  └────────────────┘
```

The SDK is a **programmatic equivalent** of the Chrome extension — where the extension enforces rules visually on Hyperliquid's trade UI (pair restrictions, balance gating, position limits), the SDK enforces the same rules in code before order submission. Both ultimately rely on Vanta Network as the source of truth.

---

## 2. Key Roles

| Component | Role |
|-----------|------|
| **hyperscaled-cli** | Command-line interface for interactive and scripted use |
| **hyperscaled (PyPI)** | Python package for programmatic integration, agent frameworks, notebooks |
| **Vanta Network** | Enforcement layer — all trades, rules, and funded-account logic pass through it (maps to `vanta-network/` repo, validator on port 48888, miner on port 8088) |
| **Hyperliquid** | Execution venue — source of truth for orders and fills (the exchange the extension injects into at `app.hyperliquid.xyz`) |
| **Hyperscaled API** | Multi-tenant entity miner platform — pricing, registration, payouts (new backend service, not yet in the repos) |

---

## 3. Design Principles

1. **Agent-first** — Every feature callable programmatically with no human in the loop
2. **Permissionless entry** — No KYC required to start trading; KYC only gates payouts
3. **Rule-enforced** — Local validation before submission where possible; clear errors on violation
4. **Transparent** — All rules, limits, and enforcement logic are queryable and inspectable
5. **OSS-friendly** — Integrate with existing open-source tooling (QuantConnect, Hyperliquid SDK)

---

## 4. Package Structure

```
hyperscaled/
├── cli/                    # CLI entry points (Click or Typer)
│   ├── data.py             # Data provider commands
│   ├── backtest.py         # Backtesting commands
│   ├── account.py          # HL account setup & funding
│   ├── miners.py           # Entity miner browsing
│   ├── register.py         # Funded account purchase & connection
│   ├── trade.py            # Trade submission
│   ├── positions.py        # Open & historical positions/orders
│   ├── info.py             # Account info, payout history
│   ├── kyc.py              # KYC flow
│   └── rules.py            # Network rules
├── sdk/                    # Python SDK (importable)
│   ├── client.py           # Main HyperscaledClient class
│   ├── data.py             # DataProvider interface
│   ├── backtest.py         # Backtesting integration
│   ├── account.py          # Account management
│   ├── trading.py          # Trade submission & validation
│   ├── portfolio.py        # Positions, orders, account info
│   ├── payouts.py          # Payout history & KYC
│   └── rules.py            # Rule engine & validation
├── models/                 # Pydantic models for all data types
└── exceptions.py           # Custom exceptions for rule violations
```

### Core dependencies

| Package | Purpose |
|---------|---------|
| Hyperliquid Python SDK | Direct HL interaction (orders, account queries) |
| x402 | Payment processing during funded account purchase |
| Privado ID SDK | KYC flow |
| QuantConnect Lean | Backtesting integration |
| Click or Typer | CLI framework |
| Pydantic | Data validation and models |
| httpx | Async API calls to Hyperscaled/Vanta endpoints |

### Configuration

Local config file at `~/.hyperscaled/config.toml` stores: HL wallet address, HL API key, payout wallet address, active entity miner selection, funded account ID, and KYC status. No sensitive keys stored — wallet signing uses the user's local wallet or environment variables.

---

## 5. Feature Specifications

### 5.1 Data Providers

Access market data from private partner providers, OSS sources, and Hyperliquid native data (orderbook, trades, funding rates).

```bash
hyperscaled data providers                              # List available providers
hyperscaled data subscribe <provider>                   # Connect to a provider
hyperscaled data stream <provider> <pairs>              # Stream real-time data
hyperscaled data historical <provider> <pair> --from <date> --to <date>
```

```python
from hyperscaled import HyperscaledClient

client = HyperscaledClient()
providers = client.data.list_providers()
stream = client.data.stream("provider_name", pairs=["BTC-USD", "ETH-USD"])
historical = client.data.get_historical("provider_name", "BTC-USD", start, end)
```

Provider types: private partners (API key gated), OSS providers (free, community-maintained), and Hyperliquid native.

---

### 5.2 Backtesting (QuantConnect Integration)

Backtest strategies using QuantConnect Lean with Vanta Network constraints (leverage limits, pair restrictions) applied so results reflect real funded-account behavior.

```bash
hyperscaled backtest init <strategy_name>
hyperscaled backtest run <strategy_file> --data <provider> --period <range>
hyperscaled backtest results <run_id>
```

```python
result = client.backtest.run(
    strategy_file="my_strategy.py",
    data_provider="hyperliquid",
    start_date="2025-01-01",
    end_date="2025-12-31",
    initial_capital=100000
)
print(result.sharpe_ratio, result.max_drawdown, result.total_return)
```

Integration approach: wraps Lean CLI locally, provides a Hyperscaled data adapter for HL orderbook data, applies Vanta rules as constraints during backtesting.

---

### 5.3 Hyperliquid Account Setup & Funding

Set up a Hyperliquid account and ensure it meets the $1,000 minimum balance. This maps to the same balance-gating logic the Chrome extension enforces in `content.js` (the `LOW_BALANCE_THRESHOLD` and blocking overlay), but done programmatically.

```bash
hyperscaled account setup
hyperscaled account fund --amount <usdc_amount>
hyperscaled account check
hyperscaled account status
```

```python
account = client.account.setup(wallet_address="0x...")
client.account.fund(amount=1000)
balance = client.account.check_balance()
# {balance: 1000.0, meets_minimum: True, minimum_required: 1000.0}
```

Continuous monitoring available via `client.account.watch_balance(callback)`. Pre-trade validation rejects orders if balance is below minimum.

---

### 5.4 Entity Miner Discovery

Browse all entity miners on Hyperscaled with pricing, profit splits, and payout configuration. In the existing codebase, entity miners are managed by `vanta-network/entity_management/` — each entity hotkey can manage subaccounts, while Hyperscaled owns the marketplace/catalog layer that traders browse. `SDK-005` should surface that catalog data to end users.

```bash
hyperscaled miners list
hyperscaled miners info <miner_slug>
hyperscaled miners compare
```

```python
miners = client.miners.list_all()  # List[EntityMiner]
miner = client.miners.get("vantatrading")
print(miner.pricing_tiers)   # [{size: 25000, cost: 150, profit_split: {...}}, ...]
print(miner.payout_cadence)  # "weekly"
```

Each `EntityMiner` should include miner-owned catalog fields only: name, slug, pricing tiers, payout cadence, optional branding metadata, and derived available account sizes. If profit split differs by account size, it should live on each pricing tier rather than as a single miner-wide field.

**Data source:** Hyperscaled API (ENG-B-002) — a miner catalog service layered above the underlying Vanta entity infrastructure. Trading rule data such as supported pairs and leverage limits remains Vanta-owned/global rule data and should be surfaced later through the rules/account surfaces, not bundled into miner discovery.

---

### 5.5 Funded Account Purchase & Connection

Purchase a funded account through a specific entity miner, connecting it to the user's Hyperliquid wallet. This is the programmatic version of the registration flow being built on the Next.js landing page.

```bash
hyperscaled register --miner <slug> --size <account_size>
hyperscaled register status
```

```python
registration = client.register.purchase(
    miner_slug="vantatrading",
    account_size=100000,
    hl_wallet="0x...",
    payout_wallet="0x..."  # Defaults to payment wallet
)
# {status: "pending", registration_id: "...", estimated_time: "~30s"}

status = client.register.check_status(registration.registration_id)
# {status: "registered", funded_account_id: "...", account_size: 100000}
```

**Flow:**
1. Validates HL wallet balance >= $1,000 before purchase
2. Payment routed via x402 to the entity miner's USDC wallet
3. Registration pipeline creates a subaccount on Vanta Network (maps to `vanta-network`'s `/entity/create-subaccount` and `/entity/register` endpoints)
4. Polls registration status until complete

---

### 5.6 Trade Submission

Submit trades on Hyperliquid that translate into funded-account positions governed by Vanta Network rules. The SDK enforces the same constraints the Chrome extension enforces visually.

```bash
hyperscaled trade submit --pair BTC-USDC --side long --size 200 --type market
hyperscaled trade submit --pair ETH-USDC --side short --size 100 --type limit --price 3500
hyperscaled trade cancel <order_id>
hyperscaled trade cancel-all
```

```python
order = client.trade.submit(
    pair="BTC-USDC",
    side="long",
    size=200,
    order_type="market",
    take_profit=105000,
    stop_loss=95000
)
# {hl_order_id: "...", funded_equivalent_size: 20000, status: "filled",
#  fill_price: 100250.50, scaling_ratio: 100.0}
```

**Pre-submission validation (local rule enforcement):**

| Check | Error | Codebase parallel |
|-------|-------|-------------------|
| Pair supported for account type | `UnsupportedPairError` | Extension's `ALLOWED_SYMBOLS` in `content.js` (BTC, ETH, SOL, XRP, DOGE, ADA) |
| Position size within leverage limits | `LeverageLimitError` | Extension's capacity % checks (62.5% single / 125% total) |
| HL balance >= $1,000 | `InsufficientBalanceError` | Extension's `LOW_BALANCE_THRESHOLD` and blocking overlay |
| Funded account notional exposure not exceeded | `ExposureLimitError` | — |

**Translation logic:** Order placed on HL at specified size → Vanta Network translates to funded account size using ratio `funded_account_size / hl_account_balance`. Partial fills guaranteed at minimum.

---

### 5.7 Rule Violation Errors

Clear, actionable errors when trades or actions violate Vanta Network rules.

```python
class HyperscaledError(Exception): ...
class RuleViolationError(HyperscaledError): ...
class UnsupportedPairError(RuleViolationError): ...
class LeverageLimitError(RuleViolationError): ...
class InsufficientBalanceError(RuleViolationError): ...
class ExposureLimitError(RuleViolationError): ...
class DrawdownBreachError(RuleViolationError): ...
class OrderFrequencyError(RuleViolationError): ...
class AccountSuspendedError(RuleViolationError): ...
```

Each error includes `.pair`, `.message`, `.rule_id`, and relevant context (current value, limit, supported values). CLI displays formatted output; `--strict` flag exits silently (exit code 1) for scripted pipelines.

---

### 5.8 Positions & Orders

Query current and historical positions and orders.

```bash
hyperscaled positions open               # Table of open positions
hyperscaled positions open --json        # JSON for agents
hyperscaled positions history --from <date> --to <date>
hyperscaled orders open
hyperscaled orders history --from <date> --to <date> --pair BTC-USDC
```

```python
positions = client.portfolio.open_positions()
# List[Position]: symbol, side, size, position_value, entry_price, mark_price,
#   liquidation_price, unrealized_pnl, take_profit, stop_loss, open_time

history = client.portfolio.position_history(start_date, end_date, pair=None)
# List[ClosedPosition]: adds realized_pnl, close_time
```

**Data source:** Permissionless read from the Vanta Network validator endpoint — maps to existing `/miner-positions/<id>` and `/orders/<id>` endpoints on port 48888. No authentication required.

---

### 5.9 Account Information

Full account status and configuration.

```bash
hyperscaled account info
hyperscaled account limits
```

```python
info = client.account.get_info()
# AccountInfo:
#   status: "active" | "suspended" | "pending_kyc" | "breached"
#   funded_account_size, hl_wallet_address, payout_wallet_address,
#   entity_miner, current_drawdown, max_drawdown_limit (-10%),
#   leverage_limits: {account_level: 20x, position_level: {...}},
#   hl_balance, funded_balance, kyc_status
```

**Data source:** Combines data from validator statistics (`/statistics/<id>`), entity subaccount dashboard (`/entity/subaccount/<hotkey>`), and collateral balance (`/collateral/balance/<address>`) — all existing Vanta Network endpoints.

---

### 5.10 Payout History

View all payout records and pending payouts.

```bash
hyperscaled payouts history
hyperscaled payouts pending
hyperscaled payouts history --json
```

```python
payouts = client.payouts.history()
# List[Payout]: date, amount, token ("USDC"), network, tx_hash,
#   status: "completed" | "pending" | "processing" | "failed"

pending = client.payouts.pending()
# Estimated next payout amount and date
```

Payouts in Vanta Network are weekly, targeting completion by midnight Sunday. Maps to the debt-based scoring system tracked in `/debt-ledger/<id>` and `/perf-ledger/<id>`.

---

### 5.11 KYC (Privado ID)

Identity verification that gates payouts (not trading).

```bash
hyperscaled kyc status
hyperscaled kyc start                    # Opens Privado ID flow
hyperscaled kyc verify
```

```python
kyc_status = client.kyc.status()
# {status: "not_started" | "pending" | "verified", provider: "privado_id"}

kyc_url = client.kyc.start()
# Returns URL; for agents, supports a callback URL for verification webhook

is_verified = client.kyc.is_verified()  # bool
```

---

### 5.12 Rules Reference

Programmatic access to all Vanta Network rules. In the existing codebase, rules are partially hardcoded in the Chrome extension (`content.js`) and enforced server-side by validators in `vanta-network`. This SDK makes them queryable and uses them for local pre-validation.

```bash
hyperscaled rules list
hyperscaled rules list --category leverage
hyperscaled rules check <pair> <size>    # Validate a hypothetical trade
```

```python
rules = client.rules.list_all()
# List[Rule]: rule_id, category, description, current_value, limit, applies_to
# Categories: leverage, pairs, drawdown, exposure, order_frequency, payout

validation = client.rules.validate_trade(pair="BTC-USDC", side="long", size=500, leverage=10)
# {valid: True/False, violations: [RuleViolation, ...]}

pairs = client.rules.supported_pairs()
```

---

## 6. Backend Endpoints Required

The CLI/SDK depends on services across Hyperliquid, Vanta Network, and a new Hyperscaled API layer.

| Endpoint | Source | Auth | SDK method | Existing in codebase? |
|----------|--------|------|------------|-----------------------|
| Entity miner catalog | Hyperscaled API (ENG-B-002) | None | `miners.list_all()` | **Partial** — internal DB-backed routes exist in `hyperscaled`, but the SDK should target a stable public catalog contract |
| Registration & payment | Hyperscaled API + x402 (ENG-B-003/005) | Wallet signature | `register.purchase()` | **No** — new service needed |
| Registration status | Hyperscaled API (ENG-B-006) | None | `register.check_status()` | **No** — new service needed |
| Miner positions | Validator REST :48888 | None | `portfolio.open_positions()` | **Yes** — `/miner-positions/<id>` |
| Statistics | Validator REST :48888 | None | `account.get_info()` | **Yes** — `/statistics/<id>` |
| Entity subaccount | Validator REST :48888 | Tier 200 | `account.get_info()` | **Yes** — `/entity/subaccount/<hotkey>` |
| Collateral balance | Validator REST :48888 | None | `account.get_info()` | **Yes** — `/collateral/balance/<address>` |
| Orders | Validator REST :48888 | None | `portfolio.open_orders()` | **Yes** — `/orders/<id>` |
| Eliminations | Validator REST :48888 | None | `rules.list_all()` | **Yes** — `/eliminations` |
| Trade submission | Hyperliquid SDK (direct) | HL API key | `trade.submit()` | N/A (external) |
| Order submission to Vanta | Miner REST :8088 | None | `trade.submit()` | **Yes** — `/api/submit-order` |
| Subaccount creation | Entity miner gateway / validator REST | None | `register.purchase()` | **Yes** — entity miner gateway work exists in `vanta-network` and proxies to validator subaccount creation endpoints |
| Rule set | Vanta Network API | None | `rules.list_all()` | **Partial** — rules exist in validator logic but no dedicated endpoint |
| Payout history | Validator REST :48888 | None | `payouts.history()` | **Partial** — `/perf-ledger/<id>`, `/debt-ledger/<id>` |
| KYC | Privado ID (ENG-B-015) | Wallet signature | `kyc.start()` | **No** — external integration |

---

## 7. Agent Integration Patterns

### 7.1 Trading Agent Loop

```python
from hyperscaled import HyperscaledClient
from hyperscaled.exceptions import RuleViolationError

client = HyperscaledClient(hl_wallet="0x...")

while True:
    signal = my_strategy.generate_signal()

    if signal:
        try:
            order = client.trade.submit(
                pair=signal.pair, side=signal.side, size=signal.size
            )
            log(f"Order filled: {order.funded_equivalent_size} on funded account")
        except RuleViolationError as e:
            log(f"Rule violation: {e.message}")

    positions = client.portfolio.open_positions()
    account = client.account.get_info()

    if account.current_drawdown < account.max_drawdown_limit * 0.8:
        log("WARNING: Approaching max drawdown")
```

### 7.2 MCP Server Integration

The SDK can be wrapped as MCP server tools, letting LLM agents (Claude, etc.) trade on Hyperscaled through tool use:

```python
tools = [
    {"name": "list_miners",    "fn": client.miners.list_all},
    {"name": "submit_trade",   "fn": client.trade.submit},
    {"name": "get_positions",  "fn": client.portfolio.open_positions},
    {"name": "get_account",    "fn": client.account.get_info},
    {"name": "get_rules",      "fn": client.rules.list_all},
]
```

---

## 8. Installation & Quick Start

### Install

```bash
pip install hyperscaled
```

Installs both the Python SDK and `hyperscaled` CLI.

### CLI Quick Start

```bash
hyperscaled config set wallet 0xYourHLWallet
hyperscaled account check
hyperscaled miners list
hyperscaled register --miner vantatrading --size 100000
hyperscaled trade submit --pair BTC-USDC --side long --size 200 --type market
hyperscaled positions open
```

### SDK Quick Start

```python
from hyperscaled import HyperscaledClient

client = HyperscaledClient(hl_wallet="0x...", payout_wallet="0x...")

miners = client.miners.list_all()
client.register.purchase(miner_slug="vantatrading", account_size=100000)

order = client.trade.submit(pair="BTC-USDC", side="long", size=200)
print(f"Funded size: ${order.funded_equivalent_size}")

for pos in client.portfolio.open_positions():
    print(f"{pos.symbol} {pos.side} uPnL: {pos.unrealized_pnl}")
```

---

## 9. Open Questions

| Area | Question |
|------|----------|
| Rate limiting | What client-side rate limits should the SDK enforce to complement server-side DDoS protection (ENG-B-010a)? |
| WebSocket support | Should v1 support WebSocket streaming for real-time position updates (Vanta Network already has a WS server on port 8765), or is polling sufficient? |
| Multi-account | Should the SDK support managing multiple funded accounts under different entity miners simultaneously? |
| Data providers | Which private data providers are confirmed for launch? |
| QuantConnect version | Which Lean version to target? Custom data adapter needed for Hyperliquid? |
| Offline validation | Cache rule sets locally for offline validation, or always fetch fresh? |
| Language support | Python-only for v1, or also TypeScript/JavaScript for web-based agents? |
