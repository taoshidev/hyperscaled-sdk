# Hyperscaled CLI & SDK — Sprint 2 Tickets

Sprint 2 is the second of three sprints in Phase 1. See [Hyperscaled CLI & SDK Design V2.md](../Hyperscaled%20CLI%20%26%20SDK%20Design%20V2.md) for the updated design reference and [OVERVIEW.md](../OVERVIEW.md) for how the existing repos fit together.

---

## Phase Overview

### Phase 1 — Funded Account Registration and Trading (Sprints 04–06)

Everything a trader or agent needs end-to-end: signup, funded account purchase, Hyperliquid wallet setup, registration status tracking, trading, and account monitoring. Consumes backend APIs from ENG-B-002 through ENG-B-016 and direct Hyperliquid SDK integrations where needed.

**Target:** Complete by end of Sprint 2026.06 (04/07)

| Sprint | Dates | Backend APIs Available | CLI/SDK Focus |
|--------|-------|------------------------|---------------|
| 2026.04 | 02/24 – 03/10 | ENG-B-002 (miner config), ENG-B-008/009 (validator endpoints) | Package foundation, config, core client, miner discovery |
| **2026.05** | **03/11 – 03/24** | **ENG-B-003 (x402), ENG-B-004 (wallet capture), ENG-B-005 (registration pipeline), ENG-B-006 (status polling)** | **Wallet validation, HL account setup, balance checks, purchase & registration flow** |
| 2026.06 | 03/25 – 04/07 | ENG-B-015 (KYC/Privado ID), ENG-B-016 (payout execution) | Trade submission, portfolio, account info, rules, payouts, KYC |

### Phase 2 — Data and Backtesting (Sprints 07–12)

Data providers, local backtesting, and the research-to-live workflow described in the V2 design.

**Target:** Complete by end of Sprint 2026.12 (06/30)

---

## Sprint 2026.05 (03/11 – 03/24) — Wallet Setup + Funded Account Registration

**Goal:** Turn the SDK and CLI from read-only discovery tools into an end-to-end registration client: validate Hyperliquid wallets, configure a trader's HL account locally, verify the minimum balance requirement, purchase a funded account, and track registration through completion.

This sprint introduces the first write-paths in the CLI/SDK. It depends on the shared client/models foundation from Sprint 1 and adds direct Hyperliquid balance checks plus backend integrations for payment, wallet capture, registration, and status polling.

---

### SDK-006 — HL wallet validation

Validate that a provided wallet address is a valid Hyperliquid address format before any registration attempt. This should be a local validation step with no backend round-trip and should reuse the same EVM-style format check already referenced in Sprint 1.

**SDK interface (`sdk/account.py`):**

```python
class AccountClient:
    def validate_wallet(self, address: str) -> bool:
        """Return True if the address is a valid Hyperliquid wallet format."""
```

**CLI wiring:**

```bash
# Existing config flow should reject invalid HL addresses before writing
hyperscaled config set wallet.hl_address 0x...

# Registration flow should reject invalid addresses before payment/submit
hyperscaled register --miner vantatrading --size 100000
```

**Validation rule:**
- Use the same address format already established for Sprint 1 and the Chrome extension: `^0x[a-fA-F0-9]{40}$`
- Validation should happen before any attempt to call ENG-B-004 or ENG-B-005
- The same helper should be reused by config writes, `account setup`, and registration prompts

**Implementation decisions (confirmed from existing repos/docs):**
- Keep `SDK-006` as a strict local format validator only. Do not add checksum logic, backend validation, or Hyperliquid API calls in this ticket.
- Standardize on the already-established regex `^0x[a-fA-F0-9]{40}$`. This same rule already appears in Sprint 1 docs, Sprint 2 docs, the Chrome extension, the web app validation helper, Vanta config, and the current SDK config layer.
- Extract or expose one shared SDK-side helper for HL/EVM-style address validation, then have `AccountClient.validate_wallet()` delegate to that helper instead of duplicating the regex.
- Preserve the current CLI failure pattern for invalid config writes: fail fast, print a clear human-readable error, and exit with a non-zero code.
- Keep `AccountClient.validate_wallet(address)` as a pure `bool` API. User-facing command flows such as `config set`, `account setup`, and `register` should be responsible for turning a failed validation into a CLI error/exception path.
- Preserve current SDK strictness on exact input. `SDK-006` should validate the provided string as-is rather than silently trimming or normalizing it.
- Treat balance checks, wallet persistence flows beyond config validation, and registration/payment wiring as out of scope for `SDK-006`; those belong to `SDK-007` and `SDK-008`.

**Why these decisions:**
- They align `SDK-006` with behavior that is already documented and partially implemented instead of introducing a second wallet-validation rule.
- The SDK config system already validates wallet addresses on load and `config set`, so the main job here is to centralize and reuse that logic across the new account and registration surfaces.
- The V2 design already reserves `sdk/account.py`, and `HyperscaledClient` already reserves the `client.account` namespace, so exposing `validate_wallet()` there matches the planned public API without changing the product shape.
- Keeping `validate_wallet()` pure and local makes it easy to test and reuse in later Sprint 2 flows before any network call or payment attempt.
- Avoiding implicit normalization keeps CLI/SDK behavior explicit and prevents hidden mutations of user input; if trimming is ever desired later, it should be a deliberate product decision applied consistently across surfaces.

**Acceptance criteria:**
- `client.account.validate_wallet(address)` returns `True`/`False` with no network dependency
- Invalid HL wallet addresses are rejected by `config set wallet.hl_address`
- Invalid HL wallet addresses are rejected in the registration CLI flow before payment or submission
- SDK and CLI use one shared validation implementation, not duplicated regexes
- Unit tests cover valid, invalid, mixed-case, malformed, and empty-string inputs

| | |
|---|---|
| **Label** | Feature |
| **Priority** | High |
| **Depends on** | SDK-003 |
| **Backend dependency** | ENG-B-004 (wallet capture consumes validated address) |
| **Estimate** | 0.5 day |

---

### SDK-007 — HL account setup & balance check

Add the account-management surface for configuring the SDK against a specific Hyperliquid wallet and checking whether that wallet meets the minimum funded-account requirement. This mirrors the balance-gating behavior already present in the Chrome extension, but exposes it in both the Python SDK and CLI.

**SDK interface (`sdk/account.py`):**

```python
class AccountClient:
    async def setup(self, wallet_address: str) -> None:
        """Configure the SDK for a Hyperliquid wallet and persist it locally."""

    async def check_balance(self) -> dict[str, object]:
        """Return current balance and whether the wallet meets the minimum."""

    async def watch_balance(self, callback) -> None:
        """Continuously poll balance and invoke callback on updates."""
```

**Expected result shape:**

```python
{
    "balance": Decimal("1250.42"),
    "meets_minimum": True,
    "minimum_required": Decimal("1000.00"),
}
```

**CLI commands (`cli/account.py`):**

```bash
hyperscaled account setup 0x...
hyperscaled account check
hyperscaled account check --json
```

**Behavior notes:**
- `account setup` should validate the wallet first, then persist it to local config
- `check_balance()` should use the configured HL wallet unless one is explicitly overridden
- The minimum required balance is `$1,000`, matching the existing extension gating logic
- `InsufficientBalanceError` should be raised by pre-trade flows when the configured balance is below the minimum

**Acceptance criteria:**
- `client.account.setup(wallet_address)` validates and saves the HL wallet to config
- `client.account.check_balance()` returns `balance`, `meets_minimum`, and `minimum_required`
- `hyperscaled account setup` writes the wallet only if validation passes
- `hyperscaled account check` prints a clear pass/fail result and current balance
- `watch_balance(callback)` continuously emits updated balance states until cancelled
- Trade and registration flows can reuse the same balance-check helper instead of duplicating logic
- Mock-based tests cover healthy balance, insufficient balance, missing wallet config, and Hyperliquid API failure handling

| | |
|---|---|
| **Label** | Feature |
| **Priority** | High |
| **Depends on** | SDK-003, SDK-004, SDK-006 |
| **Estimate** | 1 day |

---

### SDK-008 — Funded account purchase (SDK + CLI)

Implement the write path that purchases a funded account, validates the user's Hyperliquid wallet and balance, routes payment via x402, and submits the registration request into the backend registration pipeline.

**SDK interface (`sdk/register.py`):**

```python
class RegisterClient:
    async def purchase(
        self,
        miner_slug: str,
        account_size: int,
        hl_wallet: str,
        payout_wallet: str,
    ) -> dict[str, object]:
        """Purchase a funded account and return pending registration info."""
```

**Expected result shape:**

```python
{
    "status": "pending",
    "registration_id": "reg_123",
    "estimated_time": "2-5 minutes",
}
```

**CLI command (`cli/register.py`):**

```bash
hyperscaled register --miner vantatrading --size 100000
```

**Interactive CLI flow:**
1. Load miner pricing for the selected account size
2. Confirm pricing with the user
3. Validate HL wallet format
4. Check HL wallet balance is at least `$1,000`
5. Trigger x402 payment to the entity miner's USDC wallet
6. Submit registration request with HL wallet + payout wallet
7. Print pending registration state and estimated completion time

**Integration notes:**
- Payment routing depends on ENG-B-003
- Wallet capture and registration payload depend on ENG-B-005
- HL wallet validation must reuse `client.account.validate_wallet()`
- Balance gating must reuse `client.account.check_balance()`
- If balance is below the minimum, raise `InsufficientBalanceError` before payment is attempted

**Acceptance criteria:**
- `client.register.purchase(...)` validates wallet input before any backend call
- Purchase fails fast with `InsufficientBalanceError` when HL balance is below `$1,000`
- Successful purchase triggers x402 payment, then creates a pending registration
- CLI registration flow is interactive and shows the user price, wallet, and pending registration details
- The HL wallet is passed through to the backend registration pipeline exactly once after local validation
- Structured errors are returned for payment failure, registration failure, invalid miner slug, and unsupported account size
- Mock-based tests cover the full happy path and each failure branch without live payment or backend dependencies

| | |
|---|---|
| **Label** | Feature |
| **Priority** | High |
| **Depends on** | SDK-003, SDK-004, SDK-006, SDK-007 |
| **Backend dependency** | ENG-B-003, ENG-B-005 |
| **Estimate** | 1.5 days |

> **🔄 Sync required:** Confirm the ENG-B-003 and ENG-B-005 contracts before implementation starts. Specifically align on x402 payment target fields, registration payload shape, `registration_id` issuance, and the exact backend status values the CLI should expect after submission.

---

### SDK-009 — Registration status polling (SDK + CLI)

Expose the registration tracking surface so scripts and CLI users can poll a registration until it reaches a terminal state. On success, persist the resulting funded account ID into local config so later trade/account commands can use it automatically.

**SDK interface (`sdk/register.py`):**

```python
class RegisterClient:
    async def check_status(self, registration_id: str) -> dict[str, object]:
        """Fetch the current registration status from the backend."""
```

**Expected result shape:**

```python
{
    "status": "registered",
    "funded_account_id": "fa_123",
    "account_size": 100000,
}
```

**CLI command (`cli/register.py`):**

```bash
hyperscaled register status <registration_id>
hyperscaled register status --json
```

**Behavior notes:**
- The SDK should poll ENG-B-006 until the registration reaches `registered` or an error state
- The CLI should present intermediate states clearly, such as `pending` or `processing`
- On success, save `funded_account_id` into local config for downstream account/trading flows
- The register command from SDK-008 can reuse this same polling surface when running in an interactive wait mode

**Acceptance criteria:**
- `client.register.check_status(registration_id)` returns structured status data
- CLI status command displays current registration state and account size
- Successful completion persists `funded_account_id` to local config
- Polling stops on `registered` or `failed` and surfaces a clear terminal result
- Missing/unknown registration IDs are handled cleanly
- Mock-based tests cover pending, processing, registered, failed, and timeout/error cases

| | |
|---|---|
| **Label** | Feature |
| **Priority** | High |
| **Depends on** | SDK-008 |
| **Backend dependency** | ENG-B-006 |
| **Estimate** | 1 day |

---

## Sprint 2 Summary

| Ticket | Title | Depends on | Priority | Estimate |
|--------|-------|------------|----------|----------|
| SDK-006 | HL wallet validation | SDK-003 | High | 0.5 day |
| SDK-007 | HL account setup & balance check | SDK-003, SDK-004, SDK-006 | High | 1 day |
| SDK-008 | Funded account purchase (SDK + CLI) | SDK-003, SDK-004, SDK-006, SDK-007 | High | 1.5 days |
| SDK-009 | Registration status polling (SDK + CLI) | SDK-008 | High | 1 day |

**Total estimate:** 4 days

**Parallelism:** `SDK-006` can start immediately on top of the Sprint 1 client foundation. `SDK-007` can follow once validation is in place. `SDK-008` and `SDK-009` are mostly sequential because purchase must create the registration being polled, but backend contract alignment and mocks can be prepared in parallel.

```text
SDK-006 ── SDK-007 ── SDK-008 ── SDK-009
```

**Sprint 05 exit criteria:**
- HL wallet validation is enforced consistently across config, account setup, and registration
- `hyperscaled account setup` and `hyperscaled account check` work with the configured Hyperliquid wallet
- Registration purchase validates balance >= `$1,000` before payment
- `hyperscaled register --miner ... --size ...` can create a pending registration through the backend flow
- `hyperscaled register status` can track registration to completion and persist `funded_account_id`
- `InsufficientBalanceError` is available and reused by pre-trade checks
- CI green: lint, type-check, and tests passing for all new account/register flows

---

## What's Next

> **🔄 Sprint 06 prep:** Before Sprint 2026.06 starts, align SDK and backend naming for account state, funded account identifiers, and terminal registration statuses so the trading, rules, and portfolio surfaces build on the same lifecycle model defined in the V2 design doc.

**Sprint 2026.06 (03/25 – 04/07)** completes Phase 1:

- Trade submission with local rule enforcement and pre-trade account checks
- Open positions, historical orders, and account-state inspection
- Payout history and KYC status/integration
- Rules reference and trade validation surfaces for agents
