# SDK-005 Follow-up — Miner Discovery Compatibility

**Status:** Complete
**Date:** 2026-03-13
**Branch:** `sdk-005/miner-discovery-compatibility` (off `sdk-008/funded-account-purchase`)
**Location:** `hyperscaled-sdk/`

---

## Summary

Applied a focused compatibility patch to the shared miner discovery client so it matches the current `hyperscaled` app API again.

This was done as follow-up work while validating `SDK-008`, because funded-account purchase depends on miner lookup and pricing tier resolution before any payment or registration request can succeed.

The current app no longer exposes the original miner catalog routes Brian's registration work assumed. The SDK now:

- prefers the current `GET /api/entity` catalog route
- falls back to the legacy `GET /api/v1/miners` route
- resolves single-miner lookups and comparisons from the catalog response rather than assuming a per-slug backend endpoint

---

## What Was Built

### New Files

```text
hyperscaled-sdk/
└── planning/
    └── reports/
        └── SDK-005-MINER-DISCOVERY-COMPATIBILITY.md
```

### Modified Files

| File | Change |
|------|--------|
| `hyperscaled/sdk/miners.py` | Updated `MinersClient` to support the current `hyperscaled` miner catalog route and keep legacy fallback behavior |
| `tests/test_miners.py` | Reworked miner discovery tests to cover the current `/api/entity` shape, legacy fallback, and catalog-based `get()` / `compare()` behavior |

---

## Details

### 1. Current app contract changed

The original SDK-005 client targeted:

- `GET /api/v1/miners`
- `GET /api/v1/miners/{slug}`

The current `hyperscaled` app now serves miner catalog data through:

- `GET /api/entity`

That route returns the full active miner catalog with embedded `tiers`, which is enough for:

- `list_all()`
- `get(slug)`
- `compare(slugs)`

without requiring a dedicated per-slug endpoint.

### 2. Catalog-first fetch strategy

`MinersClient` now uses a small compatibility layer:

1. try `GET /api/entity`
2. if that route returns `404`, fall back to `GET /api/v1/miners`
3. normalize either payload shape into the existing `EntityMiner` SDK model

This keeps the SDK usable against the current app while avoiding a breaking change for environments that still expose the older route.

### 3. `get()` and `compare()` no longer assume per-slug HTTP routes

Because the current app serves a list endpoint instead of a per-slug endpoint, the SDK now:

- loads the catalog once
- filters by `slug` in SDK code
- raises `HyperscaledError` if the requested slug is missing

This is a better fit for the current app contract and also reduces round trips for comparisons.

### 4. Why this was done during SDK-008 work

While validating Brian's `SDK-008` branch against the latest `hyperscaled` app, it became clear that purchase flow assumptions had drifted in multiple places.

Miner discovery was the first dependency to fix because `client.register.purchase(...)` needs:

- a valid miner slug
- current tier pricing
- account-size matching

before it can request x402 payment details or submit registration.

Without this compatibility patch, `SDK-008` would fail during tier resolution even if the rest of the purchase flow were updated.

---

## Acceptance Criteria Status

| Criterion | Status |
|-----------|--------|
| SDK miner discovery works against the current `hyperscaled` app catalog route | Pass |
| Legacy miner catalog route remains supported as a fallback | Pass |
| `client.miners.get(slug)` works when only a list/catalog endpoint exists | Pass |
| `client.miners.compare(slugs)` works from the same catalog payload | Pass |
| Mock-based tests cover the new compatibility behavior | Pass |

---

## Verification

Verification was run in the repo virtual environment at `hyperscaled-sdk/.venv`.

```bash
source .venv/bin/activate
pytest -q tests/test_miners.py
ruff check hyperscaled/sdk/miners.py tests/test_miners.py
```

### Results

```text
pytest -q tests/test_miners.py                    → 10 passed in 0.14s
ruff check hyperscaled/sdk/miners.py tests/test_miners.py → All checks passed!
```

---

## Test Coverage

| Test | Coverage |
|------|----------|
| `test_list_all_normalizes_current_entity_catalog_shape` | Current `/api/entity` payload normalization |
| `test_list_all_falls_back_to_legacy_catalog_route` | Backward compatibility with `/api/v1/miners` |
| `test_get_accepts_current_entity_catalog_shape` | Catalog-based single-miner lookup |
| `test_get_missing_slug_raises_hyperscaled_error` | Missing-slug error handling without a per-slug endpoint |
| `test_compare_fetches_requested_slugs_from_catalog` | Comparison using one catalog fetch |
| `test_compare_missing_slug_raises_hyperscaled_error` | Missing-slug error path for comparisons |

---

## What's Next

This compatibility patch unblocks the next `SDK-008` alignment work:

- update registration request fields to match the current app contract
- update purchase result modeling to stop fabricating `registration_id`
- align payout-wallet and status behavior with the current `hyperscaled` backend
