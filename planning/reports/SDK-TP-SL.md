# SDK-TP-SL — TP/SL and Trailing Stop Loss

**Status:** Complete
**Date:** 2026-03-31
**Depends on:** SDK-010 (trade submission), SDK-011 (trade cancellation), SDK-013 (portfolio read path)
**Plan:** `planning/SDK-TP-SL-PLAN.md`
**Spike:** `planning/reports/SDK-TP-SL-SPIKE.md`
**Location:** `hyperscaled-sdk/`

---

## Summary

Implemented real TP/SL trigger order placement on Hyperliquid, trailing stop loss support, and post-submission TP/SL management. Prior to this work, `take_profit` and `stop_loss` were pass-through metadata on the `Order` model — they were never placed on-chain. SDK-TP-SL makes them real.

This work adds:

- Native Hyperliquid trigger order placement for TP and SL after parent order fill
- OCO (one-cancels-other) linking via `positionTpsl` grouping when both TP and SL are specified
- `trailing_stop` parameter on `submit()` / `submit_async()` with initial SL computed from fill price
- `set_tp_sl()` / `set_tp_sl_async()` for post-submission TP/SL management on existing positions
- `update_trailing_stops()` / `update_trailing_stops_async()` for manual trailing SL ratcheting
- Trigger price rounding to per-asset tick size (spike-proven requirement)
- OID resolution from `frontend_open_orders()` for grouped trigger placements
- `PortfolioClient.open_orders()` mapping that properly identifies and exposes trigger orders
- CLI `--trailing-sl-percent` and `--trailing-sl-value` options on `trade submit`
- 69 mock-based tests covering all TP/SL, trailing stop, and edge-case paths

The plan was revised twice after a live Hyperliquid perps spike (2026-03-31) that validated the core architecture but revealed three exchange-level behaviors the original plan assumed incorrectly: trigger prices must be pre-rounded, grouped `positionTpsl` responses return bare strings without OIDs, and `isPositionTpsl` is unreliable.

---

## What Was Built

### New Files

```text
hyperscaled-sdk/
├── tests/
│   └── test_tp_sl.py                # 69 mock-based tests for TP/SL and trailing stop
└── planning/
    └── reports/
        └── SDK-TP-SL.md             # This report
```

### Modified Files

| File | Change |
|------|--------|
| `hyperscaled/models/trading.py` | Added `filled_size`, `trailing_stop`, `tp_order_id`, `sl_order_id`, `trigger_status`, `trigger_error` fields to `Order` model |
| `hyperscaled/sdk/trading.py` | Added trigger order helpers, trailing stop computation/validation, `set_tp_sl()`, `update_trailing_stops()`, updated `submit_async()` to place real triggers after parent fill, added `TRIGGER_PRICE_DECIMALS` map, added `_trailing_state` dict to `TradingClient.__init__` |
| `hyperscaled/sdk/portfolio.py` | `open_orders_async()` switched from `openOrders` to `frontendOpenOrders` API; `_map_hl_order()` now detects trigger orders and populates `take_profit`/`stop_loss` from `triggerPx` and maps `order_type="market"` for trigger exits |
| `hyperscaled/cli/trade.py` | Added `--trailing-sl-percent` and `--trailing-sl-value` options to `trade submit`; `_render_order()` displays trailing stop, trigger order IDs, trigger status, and trigger error |

---

## Details

### 1. Trigger order placement after parent fill

When `submit_async()` receives `take_profit`, `stop_loss`, or `trailing_stop` and the parent order fills (or partially fills), the SDK now places real Hyperliquid trigger orders:

- **Both TP + SL:** Submitted together via `Exchange.bulk_orders()` with `grouping="positionTpsl"`, which tells Hyperliquid to OCO-link them (one trigger fills → the other auto-cancels).
- **TP only or SL only:** Submitted as a single trigger via `Exchange.order()` with default grouping.

Trigger orders are `reduce_only=True` with `isMarket=True`, meaning they execute as aggressive IoC at market price when the trigger fires. The trigger size uses `filled_size` (actual executed quantity), never the originally requested size — this prevents oversizing on partial fills.

If trigger placement fails, the parent order is still returned with `trigger_status="failed"` and `trigger_error` populated. The caller can retry via `set_tp_sl()`.

### 2. Grouped placement and OID resolution

The spike (2026-03-31) proved that grouped `positionTpsl` responses return bare `"waitingForTrigger"` strings instead of `{"resting": {"oid": ...}}`. The SDK handles this by immediately calling `frontend_open_orders()` to discover the newly placed trigger OIDs using multi-field matching:

1. Filter by `coin`, `isTrigger=True`, `reduceOnly=True`, and recency (timestamp within `[pre_placement_ts, pre_placement_ts + 5s]` — `pre_placement_ts` is recorded *before* the exchange call with a 2-second backwards buffer to account for network latency and clock skew)
2. Match by `orderType` (`"Take Profit Market"` vs `"Stop Market"`), `triggerPx`, and `sz` — all compared as strings to avoid float equality issues
3. When both TP and SL are expected, prefer the candidate pair sharing the exact same timestamp (grouped orders share identical timestamps per spike observation)

The `isPositionTpsl` field is explicitly not used — the spike proved it always returns `false` even for orders placed with `grouping="positionTpsl"`.

If OIDs are not found after 3 attempts (with 500ms backoff), the trigger is reported as `trigger_status="partial_failure"` with a descriptive error.

### 3. Trigger price rounding

The spike proved that Hyperliquid rejects fractional trigger prices for certain assets (BTC trigger at `$81507.6` → `"Invalid TP/SL price."`). The SDK pre-rounds all trigger prices to the asset's accepted tick size via `_round_trigger_price()` using a maintained precision map:

| Asset | Decimal Places |
|-------|---------------|
| BTC   | 0 (integers)  |
| ETH   | 1             |
| SOL   | 2             |
| XRP   | 4             |
| DOGE  | 5             |
| ADA   | 4             |

Unknown assets raise `HyperscaledError` — fail-closed, never guess. This map covers all six supported pairs and should be extended when new pairs are added.

### 4. Trailing stop loss

Hyperliquid has no native trailing stop. The SDK implements it in two phases:

**Phase 1 (this ticket):** Place an initial SL trigger computed from fill price + trailing parameters, then provide `update_trailing_stops()` for manual ratcheting.

- `trailing_stop={"trailing_percent": 0.02}` → LONG SL at `fill_price * (1 - 0.02)`, SHORT SL at `fill_price * (1 + 0.02)`
- `trailing_stop={"trailing_value": 2000}` → LONG SL at `fill_price - 2000`, SHORT SL at `fill_price + 2000`
- When both `stop_loss` and `trailing_stop` are provided, the more protective value is used (LONG: `max`, SHORT: `min`)

**Phase 2 (follow-up):** Optional async background monitor that auto-polls and updates. Out of scope.

Trailing state is stored in-memory on `TradingClient._trailing_state`, keyed by HL asset name. State is lost on process restart — callers should re-establish via `set_tp_sl()`.

### 5. `update_trailing_stops()`

Users call this periodically to ratchet trailing stops as price moves favorably:

1. Fetch current mid price from Hyperliquid
2. Compute candidate best price (LONG: `max(old_best, current)`, SHORT: `min(old_best, current)`)
3. Compute new SL from candidate best price + trailing params
4. If new SL is more protective than current, **place new SL first**, then cancel old (safety ordering)
5. If new SL placement fails, old SL is preserved, `best_price` is **not** advanced, and state is marked `degraded` — this ensures the next poll retries the ratchet at the same level
6. If new SL placement succeeds, `best_price` is committed to the candidate value
7. If old SL cancel fails after new SL is placed, new OID is tracked but state is marked `degraded` with `partial_failure` surfaced to caller

### 6. `set_tp_sl()`

Post-submission TP/SL management on existing positions:

1. Fetch current position from HL clearinghouse to determine side and size
2. Discover existing TP/SL trigger orders via `frontend_open_orders()`
3. Cancel existing triggers (targeted by OID, not broad coin-wide cancellation)
4. Place new triggers using the same logic as `submit_async()`
5. Return new trigger OIDs + placement status

Cancellation inspects per-order cancel statuses from the `bulk_cancel` response (via `_parse_cancel_response`). If any individual cancel returns a status other than `cancelled`, `already_closed`, or `not_found`, the entire replacement is aborted with `HyperscaledError` rather than placing replacement triggers alongside stale ones.

### 7. Validation

TP/SL and trailing stop validation mirrors vanta-network's `Signal` validators:

- **LONG:** `stop_loss < entry_price < take_profit`
- **SHORT:** `take_profit < entry_price < stop_loss`
- **Trailing stop:** exactly one of `trailing_percent` (in `(0, 1)` exclusive) or `trailing_value` (> 0)

### 8. `Order` model extensions

| Field | Type | Purpose |
|-------|------|---------|
| `filled_size` | `Decimal \| None` | Actual executed quantity (used for trigger sizing) |
| `trailing_stop` | `dict \| None` | Trailing stop parameters when applicable |
| `tp_order_id` | `str \| None` | Hyperliquid OID of the placed TP trigger |
| `sl_order_id` | `str \| None` | Hyperliquid OID of the placed SL trigger |
| `trigger_status` | `Literal[...]` | `"not_requested"` / `"pending_parent_fill"` / `"placed"` / `"partial_failure"` / `"failed"` |
| `trigger_error` | `str \| None` | Human-readable error when trigger placement fails |

All new fields have safe defaults and are backward-compatible with existing code that constructs `Order` without them.

### 9. Portfolio read path

`PortfolioClient.open_orders_async()` now uses `frontendOpenOrders` instead of `openOrders`. This provides richer trigger metadata (`isTrigger`, `triggerPx`, `orderType`, `reduceOnly`, `triggerCondition`). The `_map_hl_order()` method:

- Detects trigger orders via `isTrigger=True`
- Maps `"Take Profit Market"` → `take_profit`, `"Stop Market"` → `stop_loss` from `triggerPx`
- Sets `order_type="market"` for trigger exits instead of the previous blanket `"limit"`

### 10. CLI additions

```bash
# Market order with trailing stop
hyperscaled trade submit --pair BTC-USDC --side long --size 0.01 --trailing-sl-percent 0.02

# Market order with trailing stop (absolute value)
hyperscaled trade submit --pair BTC-USDC --side long --size 0.01 --trailing-sl-value 2000

# Both --trailing-sl-percent and --trailing-sl-value → error
```

The `_render_order()` panel now displays trailing stop, TP/SL order IDs, trigger status, and trigger error when present.

---

## Acceptance Criteria Status

| Criterion | Status |
|-----------|--------|
| `submit()` with `take_profit` and `stop_loss` places real HL trigger orders after parent fill | Pass |
| Both TP+SL → `bulk_orders` with `grouping="positionTpsl"` (OCO) | Pass |
| Single TP or SL → individual `exchange.order()` trigger | Pass |
| Trigger orders are `reduce_only=True` with `isMarket=True` | Pass |
| Trigger size uses `filled_size`, not requested size | Pass |
| Grouped trigger OIDs resolved from `frontend_open_orders()` with multi-field matching | Pass |
| Trigger prices pre-rounded to per-asset tick size | Pass |
| Unknown assets in `TRIGGER_PRICE_DECIMALS` raise `HyperscaledError` (fail-closed) | Pass |
| `trailing_stop` parameter accepted and initial SL computed from fill price | Pass |
| Combined `stop_loss` + `trailing_stop` uses the more protective value | Pass |
| `set_tp_sl()` cancels existing triggers and places replacements | Pass |
| `set_tp_sl()` cancels only targeted trigger OIDs, not all stops for a coin | Pass |
| `set_tp_sl()` aborts on partial cancel failure (per-order status inspection) | Pass |
| `update_trailing_stops()` ratchets SL when price moves favorably | Pass |
| `update_trailing_stops()` uses place-new-then-cancel-old safety ordering | Pass |
| `update_trailing_stops()` does not advance `best_price` on failed placement | Pass |
| OID resolution uses pre-placement timestamp (before exchange call + 2s buffer) | Pass |
| Trigger placement failure does not roll back the parent order | Pass |
| `trigger_status` and `trigger_error` expose partial-success state to callers | Pass |
| Pending limit orders store TP/SL intent with `trigger_status="pending_parent_fill"` | Pass |
| `PortfolioClient.open_orders()` maps trigger orders with TP/SL metadata | Pass |
| CLI `--trailing-sl-percent` / `--trailing-sl-value` options work | Pass |
| TP/SL validation matches vanta-network `Signal` validators | Pass |
| Mock-based tests cover all paths without live HL API calls | Pass |

---

## Verification

```bash
python3 -m pytest tests/test_tp_sl.py -q      → 69 passed in 6.60s
python3 -m pytest tests/test_trading.py -q -k "not test_submit_insufficient_balance"
                                                → 31 passed in 4.60s
python3 -m pytest tests/test_portfolio.py -q   → 48 passed in 0.30s
python3 -m pytest tests/test_models.py -q      → 35 passed in 0.19s
```

All 69 new tests pass (67 original + 2 added during post-review fixes). All pre-existing trading (31), portfolio (48), and model (35) tests remain green. The `test_submit_insufficient_balance` failure is pre-existing (the test expects `InsufficientBalanceError` for balance $500, but `submit_async` only checks `hl_balance <= 0` — the `meets_minimum` flag is not acted on).

---

## Test Coverage

| Test Area | Count | Coverage |
|-----------|-------|----------|
| **Validation** | 11 | Trailing stop: both keys, neither key, percent out of range (0, 1, negative), value ≤ 0, valid percent, valid value. TP/SL prices: LONG SL ≥ entry, LONG TP ≤ entry, SHORT SL ≤ entry, SHORT TP ≥ entry, valid combinations |
| **Trailing computation** | 7 | LONG percent, SHORT percent, LONG value, SHORT value, merge fixed+trailing (LONG trailing more protective, LONG fixed more protective, SHORT) |
| **Trigger rounding** | 4 | BTC integer rounding, parametrized all-pairs quantization (7 cases), unknown asset raises, per-asset decimal verification |
| **Submit with triggers** | 9 | Market TP+SL, TP only, SL only, trailing SL, trailing+fixed SL, partial fill sizing, limit pending (no triggers), failure returns order, failure sets trigger_status, partial failure status |
| **Grouped placement** | 4 | positionTpsl grouping verified, single trigger path, waitingForTrigger handling, OID resolution via frontend_open_orders |
| **OID resolution** | 7 | Retry on miss (3 attempts), recency filter, exact timestamp grouping, string comparison, isPositionTpsl not relied upon, exchange timestamp before local clock still matches (pre-placement buffer), frontend_open_orders trigger fields present |
| **set_tp_sl** | 6 | On existing position, no position raises, requires ≥1 param, cancels only targeted OIDs, aborts on partial cancel failure (per-order status inspection), registers trailing state |
| **update_trailing_stops** | 5 | Ratchets on favorable move, no change on adverse move, replacement failure keeps old OID, cancel failure marks degraded, empty state returns [] |
| **Portfolio mapping** | 1 | Trigger orders mapped with TP/SL and order_type="market" |
| **Model** | 3 | Default field values, trigger field population, JSON serialization |

---

## Design Decisions

### Why TP/SL are placed after the parent order, not atomically

The HL SDK supports `grouping="normalTpsl"` for atomic parent+TP/SL submission, but this introduces complexity around error handling (partial batch success) and response parsing (multi-status). By submitting the parent first and triggers second, the existing `_parse_hl_response` logic is unchanged and the trigger step is independently retriable.

### Why trigger placement failures don't roll back the parent

The parent trade is live on Hyperliquid once submitted. Rolling it back would require a separate market close, which introduces slippage and is rarely what the user wants. Instead, the SDK surfaces failure explicitly via `trigger_status` and `trigger_error`, and the user can retry via `set_tp_sl()`.

### Why `update_trailing_stops()` places new SL before cancelling old

If the new SL placement fails, the old SL remains in effect. If the cancel-old step fails after the new SL is placed, the user temporarily has two SL orders — one will fire and close/reduce the position, and the other becomes a no-op. This is strictly safer than cancelling first and risking a window with no SL protection.

### Why trigger discovery uses multi-field matching instead of `isPositionTpsl`

The spike proved `isPositionTpsl` is always `false` in `frontend_open_orders()` even for orders placed with `grouping="positionTpsl"`. The SDK matches by `coin` + `isTrigger` + `reduceOnly` + `orderType` + `triggerPx` + `sz` + recency window. When both TP and SL are expected, candidates sharing the exact same timestamp are preferred (grouped orders share identical timestamps per spike observation).

### Why `PortfolioClient` switched to `frontendOpenOrders`

The standard `openOrders` API does not include trigger metadata (`isTrigger`, `triggerPx`, `orderType`, `triggerCondition`). `frontendOpenOrders` provides the full payload needed to distinguish regular limit orders from TP/SL trigger orders.

---

## Post-Review Fixes (2026-03-31)

Three bugs were identified during code review and fixed:

### Fix 1 (High): OID discovery timestamp filter excluded just-placed orders

`_parse_trigger_response` recorded `placement_ts` *after* `bulk_orders()` returned, but exchange-assigned timestamps are set when the exchange receives the request — before the response round-trip. The recency filter `order_ts >= placement_ts` was guaranteed to exclude the very orders it just placed.

**Fix:** `pre_placement_ts` is now recorded *before* the exchange call in `_place_tp_sl_triggers` with a 2-second backwards buffer for network latency and clock skew, then passed explicitly to `_parse_trigger_response`. Added `test_exchange_timestamp_before_local_clock_still_matches` to verify.

### Fix 2 (Medium-high): `_cancel_trigger_oids()` ignored per-order cancel failures

`_cancel_trigger_oids()` only caught transport exceptions from `bulk_cancel()` but did not inspect per-order cancel statuses in the response body. A response like `{"status": "ok", "statuses": ["success", {"error": "..."}]}` would be treated as full success, allowing replacement triggers to be placed alongside stale ones.

**Fix:** `_cancel_trigger_oids()` now calls `_parse_cancel_response()` (already in the same file) and raises `HyperscaledError` if any individual cancel returns a status other than `cancelled`, `already_closed`, or `not_found`. Added `test_set_tp_sl_aborts_on_partial_cancel_failure` to verify.

### Fix 3 (Medium-high): Failed trailing-stop replacement advanced `best_price` permanently

`update_trailing_stops_async()` set `state["best_price"] = new_best` before attempting to place the new SL. If placement failed, `best_price` was already advanced. On the next poll, the method saw no new best price and skipped the update — the ratchet was permanently stuck.

**Fix:** `best_price` is now committed only after successful SL placement. On failure, `best_price` remains at the old value so the next poll retries the ratchet at the same level. Added assertion to `test_update_trailing_stops_replacement_failure_keeps_old_oid` to verify `best_price` is unchanged after failure.

---

## Open Follow-up Items

- **Trailing stop background monitor:** An async task that calls `update_trailing_stops()` on a configurable interval. Users would start/stop via `client.trade.start_trailing_monitor()` / `stop_trailing_monitor()`.
- **TP/SL for pending limit orders:** Monitor limit order fills and auto-place triggers when they execute. Requires fill monitoring (WebSocket or polling).
- **Trailing stop state persistence:** Save `_trailing_state` to a local file so trailing stops survive process restarts.
- **TP/SL on `close()`:** When a position is closed, existing TP/SL triggers should be cancelled automatically.
- **CLI `trade set-tp-sl` command:** Expose `set_tp_sl()` as a CLI command for managing TP/SL on existing positions.
- **OCO-at-fill verification:** The spike placed and discovered trigger orders but did not test what happens when one actually fires. The SDK trusts HL's documented OCO behavior — a follow-up test could place a tight SL near market and let it trigger.
- **Pre-existing test failure:** `test_submit_insufficient_balance` in `test_trading.py` expects `InsufficientBalanceError` for balance $500 with `meets_minimum=False`, but `submit_async` only checks `hl_balance <= 0`. The `meets_minimum` flag is imported but not acted on.
