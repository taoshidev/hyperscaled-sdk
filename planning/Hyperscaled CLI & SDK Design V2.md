# Hyperscaled CLI & SDK Design V2

Created by: Arrash
Created time: March 9, 2026 2:16 PM
Category: Planning
Last edited by: Arrash
Last updated time: March 9, 2026 3:08 PM
Reviewers: Charlie Snider, Brian Kessel, Vince, Jake Barger, Daniel Gomez
Doc stage: New

## Status

Draft for engineering review, V2 of [Hyperscaled CLI & SDK Design Doc](https://www.notion.so/Hyperscaled-CLI-SDK-Design-Doc-317a5340ff908109a0d6ed06f9a8421e?pvs=21) 

## Audience

Engineering, product, protocol design, and platform teams

## Purpose

Define the architecture, scope, workflows, APIs, and phased roadmap for `hyperscaled-cli` and `hyperscaled`, the developer interface for the Hyperscaled ecosystem.

This document is intentionally thorough. It is meant to serve as the shared reference for implementation planning across SDK, backend, marketplace, settlement, and future smart contract work.

---

# 1. Executive Summary

Hyperscaled is a developer platform for agent-native trading.

At launch, it should allow agents and developers to:

- discover funded account providers
- register for funded accounts
- connect a Hyperliquid wallet
- submit trades governed by Vanta Network rules
- monitor positions, orders, payouts, and account state

Over time, it should expand into a broader system where agents can also:

- access free market data for research and backtesting
- run local backtests using QuantConnect Lean
- discover signal providers and function providers
- use those providers for free during research and challenge phases
- pay providers only after passing challenge and trading funded capital
- monetize their own signals and functions via subscription or profit split
- compose multiple providers into one strategy
- settle profit sharing programmatically

The long-term product is not just a trading SDK. It is a **provider directory, research-to-live execution layer, and commerce system for reusable trading intelligence**.

---

# 2. Product Philosophy

## 2.1 Core Product Thesis

Most trading systems are not built by one model doing everything.

They are built from layers:

- data
- features
- signals
- forecasts
- risk logic
- execution logic
- portfolio logic

Hyperscaled should reflect that reality.

Instead of treating a strategy as one monolithic bot, Hyperscaled should support a world where:

- providers publish useful outputs
- agents discover those outputs
- agents use them in research and backtesting
- agents use them in challenge accounts for free
- agents only pay when they pass challenge and trade funded capital
- providers can monetize adoption and performance

## 2.2 Core Design Principles

### Agent-first

Every important action must be available programmatically.

### Research-to-live continuity

The path from historical testing to live funded deployment should be one connected workflow.

### Free experimentation

Signals and functions must be available for free in research and challenge phases.

### Payment only after success

Monetization activates only after a strategy passes challenge and trades funded capital.

### Provider discovery is first-class

The value of the network depends not just on publishing but on discoverability.

### Composability over monoliths

The system should eventually support multiple providers contributing to one strategy.

### Progressive delivery

Phase 1 should be useful on its own. Later phases should extend the architecture naturally rather than replacing it.

---

# 3. Scope

## 3.1 In Scope

This document covers:

- CLI design
- Python SDK design
- package architecture
- provider directory and discovery
- funded account registration flows
- trading and monitoring flows
- data and backtesting workflows
- provider monetization lifecycle
- strategy manifests
- settlement design
- phased delivery plan

## 3.2 Out of Scope

This document does not fully specify:

- validator implementation details
- smart contract bytecode or chain-specific implementation
- exact backend database schema
- complete frontend UI design
- exact challenge rules for each miner
- legal or compliance policy

---

# 4. Definitions

## 4.1 Hyperscaled

The platform that coordinates developer access, provider discovery, research workflows, registration workflows, and future monetization.

## 4.2 Vanta Network

The enforcement and funded-account logic layer that governs rules, eligibility, drawdown, exposure, and payout behavior.

## 4.3 Hyperliquid

The execution venue where trades are placed.

## 4.4 Entity Miner

A funded account provider exposed through Hyperscaled.

## 4.5 Provider

A participant publishing usable outputs to the ecosystem.

Provider types:

- **data provider**: raw or normalized market data
- **indicator provider**: derived trading signals
- **function provider**: reusable logic such as risk sizing, forecasts, or execution policies

## 4.6 Strategy

A trading system that may use one or more providers.

## 4.7 Strategy Manifest

A machine-readable declaration of which providers, versions, and terms are used by a strategy.

## 4.8 Challenge Phase

The evaluation phase before the strategy is trading funded capital.

## 4.9 Funded Phase

The phase after challenge has been passed and the strategy is trading funded capital.

---

# 5. High-Level Product Roadmap

## Phase 1 — Funded Account Registration and Trading

Goal: enable agents to register for funded accounts and trade programmatically.

## Phase 2 — Data and Backtesting

Goal: enable agents to research, backtest, then go live from the same system.

## Phase 3 — Provider Monetization

Goal: allow providers to publish signals and monetize them through subscriptions or profit splits.

## Phase 4 — Composable Functions and Programmatic Settlement

Goal: support multi-provider strategies with strategy manifests and deterministic settlement.

---

# 6. System Overview

Hyperscaled has five major layers:

1. **Developer interface**
    - CLI
    - Python SDK
2. **Provider directory and discovery**
    - provider metadata
    - search
    - usage stats
    - ranking
    - capability discovery
3. **Research and execution workflows**
    - data access
    - backtesting
    - funded account registration
    - live trading
    - monitoring
4. **Strategy coordination layer**
    - strategy manifests
    - provider usage declaration
    - pricing terms
    - challenge and funded state transitions
5. **Settlement layer**
    - payouts
    - subscriptions
    - profit sharing
    - future multi-party revenue splitting

---

# 7. Flow Diagram

## 7.1 End-to-End Ecosystem Flow

```
Agents / Developers
        ↓
Hyperscaled CLI & SDK
        ↓
Provider Directory & Discovery
  • data providers
  • indicator providers
  • function providers
  • search, ranking, usage, pricing visibility
        ↓
Research Layer
  • historical data
  • backtesting
  • strategy scaffolding
        ↓
Strategy Manifest Layer
  • provider usage
  • versions
  • pricing terms
  • challenge vs funded state
        ↓
Vanta Network Rules
  • challenge/account eligibility
  • drawdown
  • leverage
  • pair restrictions
  • exposure
        ↓
Hyperliquid Execution
        ↓
Challenge / Funded Accounts
        ↓
Payouts & Settlement
  • trader payout
  • provider payout
  • subscription billing
  • future multi-party revenue sharing
```

## 7.2 Research-to-Funded Workflow

```
Discover providers
        ↓
Use data/signals for free in backtesting
        ↓
Run local Lean backtests
        ↓
Register for challenge account
        ↓
Use providers for free during challenge
        ↓
Pass challenge
        ↓
Activate funded account
        ↓
Provider monetization turns on
        ↓
Payouts / settlement
```

---

# 8. Phase-by-Phase Product Definition

## 8.1 Phase 1 — SDK for Funded Account Registration and Trading

### Objective

Enable external agents and developers to register for funded accounts and trade programmatically without depending on a web UI.

### Required capabilities

- wallet configuration
- entity discovery
- funded account purchase
- Hyperliquid wallet linking
- registration status polling
- trade submission
- local rule validation
- account state inspection
- positions and orders inspection
- payout history inspection
- KYC status inspection

### User value

A developer can automate the entire registration and trading lifecycle.

### What success looks like

A developer can write a script that:

- selects a miner
- registers for a funded account
- submits a trade
- inspects account state
- handles rule violations cleanly

---

## 8.2 Phase 2 — Data and Backtesting

### Objective

Enable a connected research-to-live workflow.

### Required capabilities

- provider directory for data providers (maybe basic to start from us)
- historical OHLCV access
- local backtesting with Lean
- strategy scaffolding
- result inspection
- promotion from backtest to challenge registration

### User value

A developer can test before deploying without stitching together multiple external systems.

### What success looks like

A developer can:

- discover a data provider
- pull historical data
- run a backtest
- inspect metrics
- register for challenge/funded trading

---

## 8.3 Phase 3 — Provider Monetization

### Objective

Enable providers to publish signals and be paid only after successful funded usage.

### Required capabilities

- provider registration
- provider discovery
- pricing metadata
- challenge/funded monetization rules
- subscriptions
- profit split terms
- provider usage tracking
- payout history for providers

### User value

A provider can publish a useful signal and get paid when strategies actually succeed.

### What success looks like

A provider can:

- register an indicator with descriptions
- expose usage metadata
- define pricing terms
- be adopted by strategies
- receive payouts only after those strategies reach funded state

---

## 8.4 Phase 4 — Composable Functions and Deterministic Settlement

### Objective

Support strategies built from multiple providers with transparent terms and payout logic.

### Required capabilities

- function providers
- strategy manifests
- version locking
- provider dependency declaration
- deterministic settlement rules
- multi-provider payout splitting
- future recursive composition support

### User value

A strategy can use multiple providers, and payouts can be allocated according to declared usage and terms.

### What success looks like

A multi-provider strategy can:

- declare dependencies
- go live
- generate funded profits
- split payouts based on the active manifest

---

# 9. Provider Directory and Discovery

## 9.1 Why This Matters

Publishing alone is not enough.

Providers need to be discoverable based on:

- what they offer
- where they work
- how they are priced
- whether they are free in research/challenge
- whether others are actually using them

The system should make it easy for an agent to answer:

**What signals can I use right now, on what assets/timeframes, under what pricing terms, and which ones are seeing meaningful usage?**

## 9.2 Provider Types

### Data providers

Examples:

- OHLCV
- orderbook
- funding
- open interest
- trades
- normalized historical datasets

### Indicator providers

Examples:

- volatility regime
- trend score
- funding divergence
- liquidation pressure
- breakout probability
- support/resistance levels

### Function providers

Examples:

- risk sizing
- execution timing
- meta-signal aggregation
- forecast models
- portfolio allocation logic

## 9.3 Discovery Requirements

Agents must be able to discover providers by:

- provider type
- output type
- asset coverage
- timeframe
- historical availability
- live availability
- pricing model
- challenge pricing behavior
- funded pricing behavior
- adoption
- reliability

## 9.4 Provider Metadata Model

Each provider entry should expose metadata such as:

- `provider_id`
- `provider_type`
- `name`
- `version`
- `description`
- `tags`
- `assets_supported`
- `timeframes_supported`
- `schema_type`
- `historical_access`
- `live_access`
- `backtest_pricing`
- `challenge_pricing`
- `funded_pricing_model`
- `funded_price_terms`
- `status`
- `usage_stats`
- `performance_stats`
- `uptime_stats`
- `owner_identity`
- `payout_wallet`

## 9.5 Usage and Adoption Stats

Usage is critical for discovery.

Useful usage stats include:

- number of backtests using this provider
- number of active challenge accounts using it
- number of funded accounts using it
- number of active strategies using it
- total monthly requests
- challenge pass rate for strategies using it
- realized funded PnL generated by strategies using it
- uptime / SLA metrics (can be verified by us keeping a live connection as a standard)

Not all of these need to ship in the first version, but the metadata model should allow for them.

## 9.6 Search and Ranking

The discovery layer should support:

### Search

By:

- keyword
- provider name
- tag
- signal name
- asset
- timeframe

### Filtering

By:

- provider type
- free for backtesting
- free for challenge
- paid only after funded
- subscription
- profit split
- historical available
- live available

### Ranking

By:

- most used
- newest
- highest uptime
- highest challenge pass rate
- highest funded adoption
- lowest cost
- recommended

---

# 10. Economic Lifecycle for Providers

## 10.1 Core Rule

Signals and functions should be:

- free in research/backtesting
- free in challenge phase
- paid only in funded phase

This is a core product rule.

## 10.2 Stage 1 — Research / Backtesting

Allowed:

- historical usage
- Lean backtests
- experimentation
- strategy construction

Pricing:

- always free

Reason:
Charging during research suppresses experimentation and prevents network growth.

## 10.3 Stage 2 — Challenge / Evaluation

Allowed:

- live challenge usage
- strategy evaluation under real conditions

Pricing:

- free

Reason:
A strategy has not yet proven itself. Most strategies fail challenge. Providers should not extract value before there is real funded success.

## 10.4 Stage 3 — Funded Trading

Allowed:

- funded capital usage
- live production deployment

Pricing:

- subscription, profit split, or both depending on provider terms

Reason:
This aligns provider incentives with actual trading success.

## 10.5 Product Implication

Every provider must declare:

- backtest pricing
- challenge pricing
- funded pricing model

For v1, the default should be:

- backtest pricing = free
- challenge pricing = free
- funded pricing model = one of:
    - free
    - subscription
    - profit_split

---

# 11. Package Architecture

## 11.1 Repository / Package Structure

```
hyperscaled/
├── cli/
│   ├── account.py
│   ├── auth.py
│   ├── backtest.py
│   ├── config.py
│   ├── data.py
│   ├── miners.py
│   ├── orders.py
│   ├── payouts.py
│   ├── positions.py
│   ├── providers.py
│   ├── register.py
│   ├── rules.py
│   ├── trade.py
│   └── kyc.py
├── sdk/
│   ├── client.py
│   ├── account.py
│   ├── backtest.py
│   ├── data.py
│   ├── miners.py
│   ├── payouts.py
│   ├── portfolio.py
│   ├── providers.py
│   ├── register.py
│   ├── rules.py
│   ├── trading.py
│   ├── kyc.py
│   ├── manifests.py
│   └── settlement.py
├── models/
│   ├── account.py
│   ├── backtest.py
│   ├── miners.py
│   ├── payouts.py
│   ├── providers.py
│   ├── registration.py
│   ├── rules.py
│   ├── strategy.py
│   └── trading.py
├── exceptions.py
├── config.py
└── __init__.py
```

## 11.2 Design Notes

- `providers.py` should exist from the beginning even if provider monetization is later-phase.
- `manifests.py` should be present early, even if initially lightweight.
- `settlement.py` can begin as a placeholder abstraction before smart contract integration exists.

---

# 12. Core Dependencies

## Phase 1 Dependencies

- Hyperliquid Python SDK
- HTTP client library such as `httpx`
- CLI framework such as `Typer`
- `pydantic` for request/response models

## Phase 2 Dependencies

- QuantConnect Lean integration
- local process execution wrappers
- data adapters

## Phase 3+ Dependencies

- wallet signature flows
- subscription billing / settlement integration
- optional contract integration libraries depending on chain choice

---

# 13. Configuration and Authentication

## 13.1 Local Config File

Recommended path:

```
~/.hyperscaled/config.toml
```

Possible fields:

```toml
wallet_address = "0x..."
payout_wallet = "0x..."
active_miner = "vantatrading"
funded_account_id = "..."
kyc_status = "not_started"
default_data_provider = "hyperliquid"
lean_path = "/usr/local/bin/lean"
environment = "production"
```

## 13.2 Auth Principles

- no private keys stored by default
- local wallet signing preferred
- API tokens only where strictly necessary
- read-only endpoints should be accessible without unnecessary auth

---

# 14. CLI Design

## 14.1 Primary Commands

```bash
hyperscaled config ...
hyperscaled account ...
hyperscaled miners ...
hyperscaled register ...
hyperscaled trade ...
hyperscaled positions ...
hyperscaled orders ...
hyperscaled payouts ...
hyperscaled kyc ...
hyperscaled rules ...
hyperscaled providers ...
hyperscaled data ...
hyperscaled backtest ...
```

## 14.2 Example Commands

### Config

```bash
hyperscaled config set wallet 0xYourWallet
hyperscaled config show
```

### Miners

```bash
hyperscaled miners list
hyperscaled miners info vantatrading
hyperscaled miners compare
```

### Registration

```bash
hyperscaled register --miner vantatrading --size 100000
hyperscaled register status
```

### Trading

```bash
hyperscaled trade submit --pair BTC-USDC --side long --size 200 --type market
hyperscaled trade cancel <order_id>
hyperscaled trade cancel-all
```

### Monitoring

```bash
hyperscaled positions open
hyperscaled positions history --from 2026-01-01 --to 2026-02-01
hyperscaled orders open
hyperscaled payouts history
```

### Rules

```bash
hyperscaled rules list
hyperscaled rules check BTC-USDC 200
```

### Providers

```bash
hyperscaled providers list
hyperscaled providers search --type indicator --asset BTC --timeframe 1h
hyperscaled providers info provider_123
hyperscaled providers usage provider_123
hyperscaled providers compare provider_123 provider_456
hyperscaled providers register
```

### Data

```bash
hyperscaled data providers
hyperscaled data historical hyperliquid BTC-USD --from 2025-01-01 --to 2025-06-01
```

### Backtesting

```bash
hyperscaled backtest init my_strategy
hyperscaled backtest run my_strategy.py --data hyperliquid --period 2025-01-01:2025-12-31
hyperscaled backtest results run_123
```

---

# 15. Python SDK Design

## 15.1 Main Client

```python
from hyperscaled import HyperscaledClient

client = HyperscaledClient(
    wallet_address="0x...",
    payout_wallet="0x..."
)
```

## 15.2 Namespaces

Recommended namespaces:

- `client.account`
- `client.miners`
- `client.register`
- `client.trade`
- `client.portfolio`
- `client.rules`
- `client.payouts`
- `client.kyc`
- `client.providers`
- `client.data`
- `client.backtest`
- `client.manifests`
- `client.settlement`

## 15.3 Example Usage

```python
miners = client.miners.list_all()

registration = client.register.purchase(
    miner_slug="vantatrading",
    account_size=100000
)

order = client.trade.submit(
    pair="BTC-USDC",
    side="long",
    size=200,
    order_type="market"
)

positions = client.portfolio.open_positions()

providers = client.providers.search(
    provider_type="indicator",
    asset="BTC",
    timeframe="1h",
    free_for_challenge=True
)
```

---

# 16. Feature Specifications

## 16.1 Miner Discovery

### Purpose

Discover funded account providers and their configurations.

### SDK

```python
miners = client.miners.list_all()
miner = client.miners.get("vantatrading")
```

### Required fields

- name
- slug
- pricing tiers
- available account sizes
- challenge terms
- payout cadence
- supported pairs
- leverage limits
- funding requirements if any

---

## 16.2 Funded Account Registration

### Purpose

Purchase and register for an account.

### SDK

```python
registration = client.register.purchase(
    miner_slug="vantatrading",
    account_size=100000,
    wallet_address="0x...",
    payout_wallet="0x..."
)
```

### Required behaviors

- validate inputs
- route payment
- invoke backend registration workflow
- poll registration status
- return structured success/failure result

### Registration states

- pending
- awaiting_payment
- processing
- registered
- failed

---

## 16.3 Trade Submission

### Purpose

Submit trades while respecting Vanta rules.

### SDK

```python
order = client.trade.submit(
    pair="BTC-USDC",
    side="long",
    size=200,
    order_type="market",
    take_profit=105000,
    stop_loss=95000
)
```

### Required validations

- supported pair
- leverage
- notional exposure
- balance / requirement checks
- account status
- drawdown breach state

### Result fields

- order id
- funded equivalent notional
- fill status
- fill price
- scaling ratio
- rule warnings if applicable

---

## 16.4 Positions and Orders

### Open positions

```python
positions = client.portfolio.open_positions()
```

### Historical positions

```python
history = client.portfolio.position_history(start_date, end_date)
```

### Open orders

```python
orders = client.portfolio.open_orders()
```

### Historical orders

```python
order_history = client.portfolio.order_history(start_date, end_date)
```

---

## 16.5 Account Information

### SDK

```python
info = client.account.get_info()
```

### Example fields

- funded account status
- miner
- wallet addresses
- account size
- current drawdown
- max drawdown
- leverage limits
- active challenge/funded state
- KYC status

---

## 16.6 Rules

### SDK

```python
rules = client.rules.list_all()
validation = client.rules.validate_trade(
    pair="BTC-USDC",
    side="long",
    size=200
)
```

### Categories

- pair restrictions
- leverage limits
- drawdown rules
- order frequency rules
- payout requirements
- challenge state restrictions

---

## 16.7 KYC

### SDK

```python
status = client.kyc.status()
url = client.kyc.start()
```

### Principle

KYC is not required to start trading, only to unlock payouts where applicable.

---

## 16.8 Payout History

### SDK

```python
history = client.payouts.history()
pending = client.payouts.pending()
```

---

## 16.9 Provider Registration

### Purpose

Allow a provider to make a signal or function discoverable.

### Provider registration means

A provider is registering itself as a source of outputs that other strategies can use.

This is not necessarily an onchain artifact registry in the early phases.

### SDK

```python
provider = client.providers.register(
    provider_type="indicator",
    name="funding_divergence_signal",
    version="1.0.0",
    assets_supported=["BTC", "ETH"],
    timeframes_supported=["5m", "1h"],
    historical_access=True,
    live_access=True,
    backtest_pricing="free",
    challenge_pricing="free",
    funded_pricing_model="profit_split",
    funded_price_terms={"share_bps": 500},
    endpoint="https://provider.example.com/signal"
)
```

### Registration states

- draft
- active
- deprecated
- paused

---

## 16.10 Provider Discovery

### SDK

```python
results = client.providers.search(
    provider_type="indicator",
    asset="BTC",
    timeframe="1h",
    free_for_backtest=True,
    free_for_challenge=True,
    funded_pricing_model="profit_split"
)
```

### Required result fields

- core metadata
- pricing model
- usage stats
- uptime stats
- example output schema
- status
- supported environments

---

## 16.11 Data Access

### SDK

```python
historical = client.data.get_historical(
    provider="hyperliquid",
    symbol="BTC-USD",
    start_date="2025-01-01",
    end_date="2025-12-31"
)
```

### Launch recommendation

Start with:

- OHLCV
- basic metadata
- normalized output model

Add richer datasets later.

---

## 16.12 Backtesting

### SDK

```python
result = client.backtest.run(
    strategy_file="my_strategy.py",
    data_provider="hyperliquid",
    start_date="2025-01-01",
    end_date="2025-12-31",
    initial_capital=100000
)
```

### Required outputs

- total return
- Sharpe
- max drawdown
- trade count
- win rate
- equity curve metadata
- logs/errors

### Longer-term requirement

Backtests should be able to reference provider-based signals used for free during research.

---

## 16.13 Strategy Manifests

### Purpose

Declare what providers a strategy uses and under what terms.

### Why manifests matter

They become the source of truth for:

- provider usage
- version tracking
- pricing state
- later settlement

### SDK

```python
manifest = client.manifests.create(
    strategy_name="btc_trend_system",
    providers=[
        {
            "provider_id": "provider_vol_regime_v2",
            "version": "2.0.0",
            "role": "indicator",
            "terms": {
                "backtest_pricing": "free",
                "challenge_pricing": "free",
                "funded_pricing_model": "profit_split",
                "share_bps": 500
            }
        }
    ]
)
```

### Minimum fields

- strategy id or name
- provider ids
- provider versions
- environment state
- provider roles
- effective terms
- validity window

---

## 16.14 Settlement Abstraction

### Phase 3 interpretation

Initially, this may just be a programmatic payout service abstraction.

### Phase 4 interpretation

This may evolve into deterministic contract-backed settlement.

### SDK

```python
preview = client.settlement.preview(manifest_id="manifest_123")
history = client.settlement.history(manifest_id="manifest_123")
```

---

# 17. Error Model

## 17.1 Required Error Hierarchy

```python
class HyperscaledError(Exception): ...
class RuleViolationError(HyperscaledError): ...
class UnsupportedPairError(RuleViolationError): ...
class LeverageLimitError(RuleViolationError): ...
class ExposureLimitError(RuleViolationError): ...
class DrawdownBreachError(RuleViolationError): ...
class AccountSuspendedError(RuleViolationError): ...
class RegistrationError(HyperscaledError): ...
class ProviderRegistrationError(HyperscaledError): ...
class ProviderDiscoveryError(HyperscaledError): ...
class BacktestError(HyperscaledError): ...
class SettlementError(HyperscaledError): ...
```

## 17.2 Error Design Principles

Errors should be:

- structured
- actionable
- machine-readable
- human-readable

Example fields:

- `code`
- `message`
- `rule_id`
- `current_value`
- `allowed_value`
- `context`

---

# 18. State Model

## 18.1 Account State

Recommended top-level states:

- research
- challenge
- funded
- suspended
- breached
- payout_blocked

## 18.2 Provider Monetization State

Monetization behavior depends on account state.

| Account State | Provider Pricing Behavior |
| --- | --- |
| research | free |
| challenge | free |
| funded | paid according to provider terms |
| suspended | no new funded monetization |
| breached | no new funded monetization |

This state model should be explicit in code and backend APIs.

---

# 19. Backend Services Required

The SDK depends on backend services such as:

- miner directory service
- registration service
- registration status service
- Vanta rule service
- account status service
- payout history service
- provider directory service
- provider usage stats service
- data provider gateway
- backtest orchestration or local adapter support
- manifest service
- settlement service

A more concrete mapping:

| Capability | Backend Dependency |
| --- | --- |
| miner discovery | Hyperscaled miner service |
| account registration | registration service + payment flow |
| status polling | registration status endpoint |
| trading | Hyperliquid SDK or execution proxy |
| rules | Vanta rules service |
| account info | Vanta / validator state endpoint |
| providers | provider directory service |
| provider usage | provider usage metrics service |
| payouts | payout history service |
| manifests | manifest service |
| settlement | settlement service |

---

# 20. Provider Commerce Model

## 20.1 Why We Should Not Charge Early

The system should not force payment:

- during backtesting
- during experimentation
- during challenge

This is important for adoption.

## 20.2 Supported Monetization Models

### Free

Provider is always free.

### Subscription

Recurring fee only once strategy is funded.

### Profit split

Provider receives a percentage of funded profits.

## 20.3 Why This Works

This model:

- reduces friction
- aligns incentives
- avoids charging before success
- encourages experimentation and adoption

---

# 21. Smart Contract Positioning

## 21.1 Early View

In the early phases, “provider registration” should mean:

- registering metadata
- exposing endpoints
- becoming discoverable
- declaring pricing terms

It does not need to mean a complex onchain artifact registry immediately.

## 21.2 Later View

As multi-provider funded strategies become important, strategy manifests and payout rights should become more formal and deterministic.

That can evolve toward smart contract settlement, but this should be built on top of a working provider directory and manifest model, not instead of it.

---

# 22. Engineering Recommendations

## 22.1 Build `providers` early

Even if monetization is later, the directory should exist early.

## 22.2 Keep manifests lightweight at first

Manifest support should begin as a declaration and tracking layer.

## 22.3 Make account state explicit

Provider pricing depends on account state. This should not be implicit.

## 22.4 Do not overbuild contracts too early

Start with provider registration, discovery, manifests, and settlement abstractions before contract-heavy designs.

## 22.5 Design for observability

Every major object should be inspectable:

- miner
- account
- provider
- manifest
- payout
- rule violation
- backtest

---

# 23. Suggested MVP Boundaries

## 23.1 Phase 1 MVP

- config
- miners
- register
- trade
- positions/orders
- payouts
- rules
- account info

## 23.2 Phase 2 MVP

- historical OHLCV
- Lean integration
- data provider abstraction
- backtest result inspection

## 23.3 Phase 3 MVP

- provider registration
- provider discovery
- provider metadata
- challenge/funded pricing metadata
- provider usage metrics
- provider payout history

## 23.4 Phase 4 MVP

- strategy manifests
- version locking
- deterministic provider terms
- multi-provider payout allocation

---

# 24. Open Questions

## Product

- Should funded providers be ranked partly by challenge pass rates?
- Should provider recommendations be personalized per strategy type?
- What metadata is mandatory for provider registration?

## Engineering

- How much provider usage data can be computed cheaply in v1?
- Should backtests be strictly local or optionally remote?
- How should provider outputs be normalized across schemas?

## Settlement

- When a strategy swaps providers mid-month, how is payout split updated?
- Should manifest updates be immediate or epoch-based?
- How should strategy/provider version mismatches be handled?

## Security

- How are provider endpoints authenticated or rate limited?
- How do we prevent fake usage inflation?
- How do we handle malicious or low-quality providers?

---

# 25. One-Sentence Product Summary

Hyperscaled is a developer platform that connects provider discovery, free research and challenge usage, funded trading, and eventual provider monetization into one agent-native trading system.

---

# 26. Quick Reference Examples

## 26.1 Funded Trading Script

```python
from hyperscaled import HyperscaledClient
from hyperscaled.exceptions import RuleViolationError

client = HyperscaledClient(wallet_address="0x...")

miners = client.miners.list_all()
client.register.purchase(miner_slug="vantatrading", account_size=100000)

try:
    order = client.trade.submit(
        pair="BTC-USDC",
        side="long",
        size=200,
        order_type="market"
    )
except RuleViolationError as e:
    print(e)
```

## 26.2 Provider Discovery Script

```python
from hyperscaled import HyperscaledClient

client = HyperscaledClient()

providers = client.providers.search(
    provider_type="indicator",
    asset="BTC",
    timeframe="1h",
    free_for_backtest=True,
    free_for_challenge=True,
    funded_pricing_model="profit_split"
)

for p in providers:
    print(p.name, p.usage_stats)
```

## 26.3 Backtest Script

```python
from hyperscaled import HyperscaledClient

client = HyperscaledClient()

result = client.backtest.run(
    strategy_file="my_strategy.py",
    data_provider="hyperliquid",
    start_date="2025-01-01",
    end_date="2025-12-31",
    initial_capital=100000
)

print(result.sharpe_ratio, result.max_drawdown, result.total_return)
```