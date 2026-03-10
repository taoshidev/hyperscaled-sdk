# Hyperscaled CLI & SDK — Sprint 1 Tickets

Sprint 1 is the first of three sprints in Phase 1. See [OLD_CLI_SDK_DESIGN.md](../OLD_CLI_SDK_DESIGN.md) for the full design and [OVERVIEW.md](../OVERVIEW.md) for how the existing repos fit together.

---

## Phase Overview

### Phase 1 — Interact with Hyperscaled (Sprints 04–06)

Everything a trader or agent needs end-to-end: signup, purchasing a funded account, submitting trades, and monitoring account info, rules, positions, and payouts. Consumes backend APIs from ENG-B-002 through ENG-B-016.

**Target:** Complete by end of Sprint 2026.06 (04/07)

| Sprint | Dates | Backend APIs Available | CLI/SDK Focus |
|--------|-------|------------------------|---------------|
| **2026.04** | **02/24 – 03/10** | ENG-B-002 (miner config), ENG-B-003 (x402), ENG-B-008/009 (validator endpoints) | **Package foundation, config, core client** |
| 2026.05 | 03/11 – 03/24 | ENG-B-004 (wallet capture), ENG-B-005 (registration pipeline), ENG-B-006 (status polling) | Miner discovery, registration & purchase |
| 2026.06 | 03/25 – 04/07 | ENG-B-015 (KYC/Privado ID), ENG-B-016 (payout execution) | Trade submission, portfolio, account info, payouts, KYC, rules |

### Phase 2 — Strategy Building Layer (Sprints 07–12)

Data providers, backtesting with QuantConnect, agent integration patterns, and the MCP server wrapper.

**Target:** Complete by end of Sprint 2026.12 (06/30)

---

## Sprint 2026.04 (02/24 – 03/10) — Foundation + Miner Discovery

**Goal:** Scaffold the full package, wire up config and the core client, and ship the entity miner browsing commands — the first user-facing feature, usable as soon as ENG-B-002 (miner config API) is live.

This sprint has no dependency on Hyperliquid or Vanta Network at runtime — it's pure infrastructure and the first read-only API integration. Everything here is a prerequisite for the registration and trading work in Sprints 05–06.

---

### SDK-001 — Package scaffold & CLI entry point

Set up the full directory structure, build tooling, and a working (empty) CLI.

**What to build:**

```
hyperscaled/
├── cli/
│   ├── __init__.py
│   ├── main.py              # Typer app with subcommand groups
│   ├── data.py              # (stub)
│   ├── backtest.py          # (stub)
│   ├── account.py           # (stub)
│   ├── miners.py            # (stub — wired in SDK-005)
│   ├── register.py          # (stub)
│   ├── trade.py             # (stub)
│   ├── positions.py         # (stub)
│   ├── info.py              # (stub)
│   ├── kyc.py               # (stub)
│   └── rules.py             # (stub)
├── sdk/
│   ├── __init__.py
│   ├── client.py            # (stub — wired in SDK-003)
│   ├── data.py              # (stub)
│   ├── backtest.py          # (stub)
│   ├── account.py           # (stub)
│   ├── trading.py           # (stub)
│   ├── portfolio.py         # (stub)
│   ├── payouts.py           # (stub)
│   └── rules.py             # (stub)
├── models/
│   └── __init__.py          # (stub — wired in SDK-004)
├── exceptions.py            # (stub — wired in SDK-004)
├── __init__.py              # Exports HyperscaledClient
└── py.typed                 # PEP 561 marker
pyproject.toml
README.md
```

**`pyproject.toml` dependencies:**

| Package | Purpose |
|---------|---------|
| `typer[all]` | CLI framework with rich output |
| `httpx` | Async HTTP client for Hyperscaled/Vanta API calls |
| `pydantic>=2` | Data validation and models |
| `tomli` / `tomli-w` | Config file read/write (TOML) |
| `hyperliquid-python-sdk` | Direct HL interaction (needed in Sprint 06) |
| `rich` | CLI table formatting and error display |

Dev dependencies: `ruff`, `mypy`, `pytest`, `pytest-asyncio`

**CI/CD:** GitHub Actions workflow with lint (ruff), type-check (mypy), and test (pytest) on push/PR.

**CLI entry point:** `hyperscaled --help` prints the top-level command groups. Subcommand stubs print "Not yet implemented" with the target sprint.

**Acceptance criteria:**
- `pip install -e .` works from the repo root
- `hyperscaled --help` shows all subcommand groups
- `hyperscaled --version` prints version from `pyproject.toml`
- CI passes with lint, type-check, and an empty test suite
- All stub modules import cleanly

| | |
|---|---|
| **Label** | Infrastructure |
| **Priority** | High |
| **Depends on** | Nothing — start immediately |
| **Estimate** | 1 day |

---

### SDK-002 — Config system (`~/.hyperscaled/config.toml`)

Local configuration for wallet addresses, active miner selection, and account state. No secrets stored — wallet signing keys come from environment variables or the user's local wallet.

**Config schema:**

```toml
[wallet]
hl_address = "0x..."        # Hyperliquid trading wallet
payout_address = "0x..."    # Wallet for receiving payouts

[account]
entity_miner = ""           # Active entity miner slug (set during registration)
funded_account_id = ""      # Funded account ID (set after purchase)
kyc_status = "not_started"  # "not_started" | "pending" | "verified"

[api]
hyperscaled_base_url = "https://api.hyperscaled.com"
```

**SDK interface:**

```python
from hyperscaled.sdk.config import Config

config = Config.load()                # Reads ~/.hyperscaled/config.toml
config.wallet.hl_address = "0x..."
config.save()                         # Writes back

# Falls back to env vars: HYPERSCALED_HL_ADDRESS, HYPERSCALED_PAYOUT_ADDRESS
```

**CLI commands:**

```bash
hyperscaled config set wallet.hl_address 0x...
hyperscaled config set wallet.payout_address 0x...
hyperscaled config show                 # Pretty-prints current config (redacts nothing — no secrets)
hyperscaled config path                 # Prints ~/.hyperscaled/config.toml path
```

**Validation:** HL address validated with the same regex the Chrome extension uses (`/^0x[a-fA-F0-9]{40}$/` — see `popup.js` line 242). Invalid addresses rejected at `config set` time.

**Acceptance criteria:**
- First run auto-creates `~/.hyperscaled/config.toml` with defaults
- `config set` validates wallet address format before writing
- `config show` displays all values in a formatted table
- Env var overrides work: `HYPERSCALED_HL_ADDRESS=0x... hyperscaled config show`
- Config is a Pydantic model so it validates on load

| | |
|---|---|
| **Label** | Feature |
| **Priority** | High |
| **Depends on** | SDK-001 |
| **Estimate** | 0.5 day |

---

### SDK-003 — `HyperscaledClient` core class

The main entry point for programmatic use. Lazy-loads sub-clients so only the features you use get initialized.

**SDK interface:**

```python
from hyperscaled import HyperscaledClient

# Loads config from ~/.hyperscaled/config.toml, overridable via constructor
client = HyperscaledClient(
    hl_wallet="0x...",            # Optional — overrides config
    payout_wallet="0x...",        # Optional — overrides config
    base_url="https://...",       # Optional — overrides config
)

# Sub-clients (lazy-loaded on first access)
client.miners       # → MinersClient (SDK-005)
client.register     # → RegisterClient (Sprint 05)
client.trade        # → TradingClient (Sprint 06)
client.portfolio    # → PortfolioClient (Sprint 06)
client.account      # → AccountClient (Sprint 06)
client.payouts      # → PayoutsClient (Sprint 06)
client.kyc          # → KYCClient (Sprint 06)
client.rules        # → RulesClient (Sprint 06)
client.data         # → DataClient (Phase 2)
client.backtest     # → BacktestClient (Phase 2)
```

**Internal wiring:**
- Manages a shared `httpx.AsyncClient` session with base URL, default headers, and timeout config
- Each sub-client receives the shared session and config reference
- Supports async context manager: `async with HyperscaledClient() as client: ...`
- Synchronous wrapper for non-async callers: methods internally run the async version via `asyncio.run()` when called outside an event loop

**Acceptance criteria:**
- `HyperscaledClient()` loads config and creates a usable instance
- Accessing an unimplemented sub-client raises `NotImplementedError` with the target sprint
- `async with` and sync usage both work
- Shared httpx session is reused across sub-clients
- Constructor overrides take precedence over config file, which takes precedence over env vars

| | |
|---|---|
| **Label** | Feature |
| **Priority** | High |
| **Depends on** | SDK-001, SDK-002 |
| **Estimate** | 1 day |

---

### SDK-004 — Pydantic models & exception hierarchy

All data types and errors the SDK uses. Defined up front so every feature ticket in Sprints 04–06 can import and use them immediately.

**Models (`models/`):**

```python
# models/miner.py
class PricingTier(BaseModel):
    account_size: int           # e.g. 25000, 50000, 100000
    cost: Decimal               # e.g. 150.00, 250.00
    profit_split: ProfitSplit   # Usually uniform across tiers, but may vary by tier

class ProfitSplit(BaseModel):
    trader_pct: int             # e.g. 80
    miner_pct: int              # e.g. 20

class EntityMiner(BaseModel):
    name: str
    slug: str
    pricing_tiers: list[PricingTier]
    payout_cadence: str         # e.g. "weekly" (normalized from backend cadence settings)
    available_account_sizes: list[int]
    brand_color: str | None = None

# models/trading.py
class Order(BaseModel):
    hl_order_id: str
    pair: str
    side: Literal["long", "short"]
    size: Decimal
    funded_equivalent_size: Decimal
    order_type: Literal["market", "limit"]
    status: Literal["filled", "partial", "pending", "cancelled"]
    fill_price: Decimal | None
    scaling_ratio: Decimal
    take_profit: Decimal | None
    stop_loss: Decimal | None
    created_at: datetime

class Position(BaseModel):
    symbol: str
    side: Literal["long", "short"]
    size: Decimal
    position_value: Decimal
    entry_price: Decimal
    mark_price: Decimal
    liquidation_price: Decimal | None
    unrealized_pnl: Decimal
    take_profit: Decimal | None
    stop_loss: Decimal | None
    open_time: datetime

class ClosedPosition(Position):
    realized_pnl: Decimal
    close_time: datetime

# models/account.py
class LeverageLimits(BaseModel):
    account_level: float
    position_level: dict[str, float]

class AccountInfo(BaseModel):
    status: Literal["active", "suspended", "pending_kyc", "breached"]
    funded_account_size: int
    hl_wallet_address: str
    payout_wallet_address: str
    entity_miner: str
    current_drawdown: Decimal
    max_drawdown_limit: Decimal   # -10% in Vanta Network
    leverage_limits: LeverageLimits
    hl_balance: Decimal
    funded_balance: Decimal
    kyc_status: Literal["not_started", "pending", "verified"]

# models/payout.py
class Payout(BaseModel):
    date: datetime
    amount: Decimal
    token: str                    # "USDC"
    network: str
    tx_hash: str | None
    status: Literal["completed", "pending", "processing", "failed"]

# models/registration.py
class RegistrationStatus(BaseModel):
    status: Literal["pending", "registered", "failed"]
    registration_id: str
    funded_account_id: str | None
    account_size: int
    estimated_time: str | None

# models/rules.py
class Rule(BaseModel):
    rule_id: str                  # e.g. "PAIR_RESTRICTION_001"
    category: Literal["leverage", "pairs", "drawdown", "exposure", "order_frequency", "payout"]
    description: str
    current_value: str | None
    limit: str
    applies_to: str | None       # account tier, pair, etc.

class RuleViolation(BaseModel):
    rule: Rule
    actual_value: str
    message: str

class TradeValidation(BaseModel):
    valid: bool
    violations: list[RuleViolation]
```

**Exception hierarchy (`exceptions.py`):**

```python
class HyperscaledError(Exception):
    """Base exception for all Hyperscaled errors."""
    message: str

class RuleViolationError(HyperscaledError):
    """A Vanta Network rule was violated."""
    rule_id: str
    limit: str
    actual_value: str

class UnsupportedPairError(RuleViolationError):
    pair: str
    supported_pairs: list[str]

class LeverageLimitError(RuleViolationError):
    requested_leverage: float
    max_leverage: float

class InsufficientBalanceError(RuleViolationError):
    balance: Decimal
    minimum_required: Decimal     # $1,000 — matches extension's LOW_BALANCE_THRESHOLD

class ExposureLimitError(RuleViolationError):
    current_exposure: Decimal
    max_exposure: Decimal

class DrawdownBreachError(RuleViolationError):
    current_drawdown: Decimal
    max_drawdown: Decimal         # -10% in Vanta Network (90-day challenge: -6%)

class OrderFrequencyError(RuleViolationError):
    requests_per_minute: int
    limit_per_minute: int

class AccountSuspendedError(HyperscaledError):
    reason: str
    suspended_at: datetime
```

**Acceptance criteria:**
- All models import cleanly and validate with sample data
- Exception hierarchy is tested: `isinstance(UnsupportedPairError(...), RuleViolationError)` is True
- Every error type exposes `.message`, `.rule_id` (where applicable), and contextual fields
- Models serialize to/from JSON (for CLI `--json` output)
- At least one unit test per model and per exception type

| | |
|---|---|
| **Label** | Feature |
| **Priority** | High |
| **Depends on** | SDK-001 |
| **Estimate** | 1 day |

---

### SDK-005 — Entity miner discovery (SDK + CLI)

The first user-facing feature. Lets traders and agents browse all entity miners on Hyperscaled — their pricing, payout cadence, profit splits, and account sizes. This is a read-only integration with the Hyperscaled miner catalog API (ENG-B-002).

**Context from the existing codebase:** Entity miners in Vanta Network (`vanta-network/entity_management/`) are hotkeys that manage subaccounts and expose operational APIs for registration/dashboard flows. The Hyperscaled API (ENG-B-002) should expose the marketplace-facing catalog for those miners: pricing tiers, payout cadence, branding, and account sizes. This SDK feature is the first client of that catalog API.

**Scope note:** `SDK-005` is intentionally limited to miner-owned catalog metadata. Trading rule fields such as supported pairs and leverage limits are Vanta-owned/global rule data and should be surfaced later through the rules/account surfaces rather than bundled into miner discovery.

**SDK interface (`sdk/miners.py`):**

```python
class MinersClient:
    async def list_all(self) -> list[EntityMiner]:
        """Fetch all entity miners from the Hyperscaled API."""

    async def get(self, slug: str) -> EntityMiner:
        """Fetch a single entity miner by slug."""

    async def compare(self, slugs: list[str] | None = None) -> list[EntityMiner]:
        """Fetch multiple miners for side-by-side comparison.
        If slugs is None, compares all miners."""
```

**CLI commands (`cli/miners.py`):**

```bash
hyperscaled miners list
# ┌─────────────────┬────────────────┬─────────────┬────────────────────┐
# │ Miner           │ Profit Split   │ Payout      │ Account Sizes      │
# │                 │                │ Cadence     │                    │
# ├─────────────────┼────────────────┼─────────────┼────────────────────┤
# │ vantatrading    │ 80/20          │ Weekly      │ $25K, $50K, $100K  │
# │ alphaquant      │ Varies by tier │ Biweekly    │ $50K, $100K, $250K │
# └─────────────────┴────────────────┴─────────────┴────────────────────┘

hyperscaled miners info vantatrading
# Name:              Vanta Trading
# Slug:              vantatrading
# Payout Cadence:    Weekly
# Profit Split:      80% trader / 20% miner (uniform across tiers)
#
# Pricing:
# ┌──────────────┬─────────┬──────────────┐
# │ Account Size │ Cost    │ Profit Split │
# ├──────────────┼─────────┼──────────────┤
# │ $25,000      │ $150    │ 80/20        │
# │ $50,000      │ $250    │ 80/20        │
# │ $100,000     │ $400    │ 80/20        │
# └──────────────┴─────────┴──────────────┘

hyperscaled miners compare
# Side-by-side table of catalog fields for all miners

hyperscaled miners list --json
# JSON output for agent consumption
```

**API contract (expected from ENG-B-002):**

```
GET /api/v1/miners           → List[EntityMiner]
GET /api/v1/miners/{slug}    → EntityMiner
```

The response shape should contain miner-owned catalog data only: name, slug, payout cadence, pricing tiers, optional branding metadata, and derived account sizes. If a miner uses the same split across all tiers, the CLI may summarize it as a single value; otherwise it should display "Varies by tier" and show the per-tier values in detailed output.

**Acceptance criteria:**
- `hyperscaled miners list` displays a formatted table of all miners
- `hyperscaled miners info <slug>` shows payout cadence and full pricing-tier detail for one miner
- `hyperscaled miners compare` shows a side-by-side comparison table of catalog fields
- `--json` flag outputs raw JSON on all commands
- `client.miners.list_all()` and `client.miners.get(slug)` work from Python
- Graceful error handling: API unreachable, miner not found (404)
- Mock-based tests for all SDK methods and CLI commands (no live API dependency)

| | |
|---|---|
| **Label** | Feature |
| **Priority** | High |
| **Depends on** | SDK-003, SDK-004 |
| **Backend dependency** | ENG-B-002 (miner config service — in progress Sprint 04) |
| **Estimate** | 1.5 days |

> **🔄 Sync required:** Confirm API contract with @Brian Kessel before starting this ticket. Need to validate that ENG-B-002's response shape matches the narrowed `EntityMiner` catalog model defined above (fields, types, naming, per-tier profit split handling, and cadence normalization). If Brian's endpoints aren't ready, proceed with mocks — but get the contract agreed so there's no rework.

---

## Sprint 1 Summary

| Ticket | Title | Depends on | Priority | Estimate |
|--------|-------|------------|----------|----------|
| SDK-001 | Package scaffold & CLI entry point | — | High | 1 day |
| SDK-002 | Config system | SDK-001 | High | 0.5 day |
| SDK-003 | `HyperscaledClient` core class | SDK-001, SDK-002 | High | 1 day |
| SDK-004 | Pydantic models & exception hierarchy | SDK-001 | High | 1 day |
| SDK-005 | Entity miner discovery (SDK + CLI) | SDK-003, SDK-004 | High | 1.5 days |

**Total estimate:** 5 days

**Parallelism:** SDK-002 and SDK-004 can start in parallel once SDK-001 is done. SDK-003 requires SDK-002. SDK-005 requires both SDK-003 and SDK-004.

```
SDK-001 ──┬── SDK-002 ── SDK-003 ──┐
          │                        ├── SDK-005
          └── SDK-004 ─────────────┘
```

**Sprint 04 exit criteria:**
- `pip install hyperscaled` works and provides a functional CLI
- `hyperscaled miners list` returns real data from ENG-B-002 (or mocked if API isn't ready)
- All models and exceptions are defined, tested, and importable
- Config system reads/writes `~/.hyperscaled/config.toml` with address validation
- `HyperscaledClient` initializes with lazy sub-clients and shared httpx session
- CI green: lint, type-check, all tests passing

---

## What's Next

> **🔄 Sync with @Brian Kessel (Sprint 05–06 prep):** Beyond ENG-B-002, the SDK consumes several more backend endpoints in Sprints 05–06: ENG-B-003 (x402), ENG-B-004 (wallet capture), ENG-B-005 (registration), ENG-B-006 (status polling), ENG-B-015 (KYC), ENG-B-016 (payouts). Align on contracts for these during Sprint 04 so the dashboard and SDK aren't building against different assumptions.

**Sprint 2026.05 (03/11 – 03/24)** picks up where this leaves off:

- **SDK-006** — HL account setup & balance checking (uses Hyperliquid SDK, mirrors the Chrome extension's balance-gating logic from `content.js`)
- **SDK-007** — Funded account purchase via x402 payment (consumes ENG-B-003, ENG-B-005)
- **SDK-008** — Registration status polling (consumes ENG-B-006)
- **SDK-009** — Wallet capture & validation during registration (consumes ENG-B-004)

**Sprint 2026.06 (03/25 – 04/07)** completes Phase 1:

- **SDK-010** — Trade submission with local rule enforcement
- **SDK-011** — Open & historical positions/orders (consumes validator REST `/miner-positions/<id>`, `/orders/<id>`)
- **SDK-012** — Account info (aggregates `/statistics/<id>`, `/entity/subaccount/<hotkey>`, `/collateral/balance/<address>`)
- **SDK-013** — Payout history (consumes `/perf-ledger/<id>`, `/debt-ledger/<id>`)
- **SDK-014** — KYC flow via Privado ID (consumes ENG-B-015)
- **SDK-015** — Rules reference & trade validation
