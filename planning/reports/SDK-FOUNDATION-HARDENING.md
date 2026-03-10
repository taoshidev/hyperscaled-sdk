# SDK Foundation Hardening

**Status:** Complete
**Date:** 2026-03-05
**Branch:** `chore/sdk-foundation-hardening` (off `main`)
**Location:** `hyperscaled-sdk/`

---

## Summary

Applied three small hardening changes before `SDK-005`:

1. Fixed config precedence so `HYPERSCALED_BASE_URL` only acts as a fallback and does not override an explicit config file value
2. Added a safe local version fallback so imports and tests work cleanly from an uninstalled checkout
3. Updated the SDK README so it no longer implies miner discovery is already implemented

This work was done to reduce risk before the first real HTTP-backed feature (`SDK-005` miner discovery) is built.

---

## What Was Changed

### Modified Files

| File | Change |
|------|--------|
| `hyperscaled/sdk/config.py` | Fixed env-var fallback behavior for `HYPERSCALED_BASE_URL` so config file values take precedence |
| `hyperscaled/__init__.py` | Switched package version lookup to shared helper with local fallback |
| `hyperscaled/cli/main.py` | Switched CLI `--version` output to shared helper with local fallback |
| `README.md` | Removed examples that implied `SDK-005` miner commands already worked; replaced with currently implemented config examples |
| `tests/test_config.py` | Added coverage for base URL precedence |
| `tests/test_client.py` | Removed two stale `type: ignore` comments surfaced during verification |

### New Files

```
hyperscaled-sdk/
├── hyperscaled/
│   └── _version.py         # Shared version lookup with local fallback
└── tests/
    └── test_version.py     # Version fallback tests
```

---

## Details

### 1. Config precedence fix

The docs and tests for `SDK-002` say config file values should override environment variables. That was true for wallet addresses but not for `HYPERSCALED_BASE_URL`, which always overwrote the file value if present in the environment.

Updated `Config.load()` / `_apply_env_fallbacks()` so environment variables are only applied when the corresponding value is absent from the loaded config file.

**Impact on `SDK-005`:** Miner discovery will rely on the shared base URL for all HTTP calls, so this avoids surprising behavior when developers have `HYPERSCALED_BASE_URL` set in their shell.

### 2. Version fallback for local development

Previously, importing `hyperscaled` required installed package metadata:

- `hyperscaled/__init__.py` called `importlib.metadata.version("hyperscaled")`
- `hyperscaled/cli/main.py` did the same for `hyperscaled --version`

That works after install, but it breaks in local/uninstalled contexts. Added `hyperscaled/_version.py` with a shared helper:

- returns the installed package version when metadata exists
- falls back to `0.0.0+local` when metadata is unavailable

This makes local test collection and imports more robust.

### 3. README cleanup

The README previously showed miner discovery examples:

- `hyperscaled miners list`
- `hyperscaled miners info <slug>`
- `client.miners.list_all()`

Those commands are still part of `SDK-005` and are not implemented yet. The README now shows currently working config-oriented examples instead and explicitly states that miner discovery is planned for `SDK-005`.

---

## Verification

Verification was re-run using the repo virtual environment at `hyperscaled-sdk/.venv`.

```bash
which python
pytest -q
ruff check .
mypy hyperscaled tests
```

### Results

```
which python              → /home/danny/hyperscaled/hyperscaled-sdk/.venv/bin/python
pytest -q                 → 108 passed, 1 warning
ruff check .              → All checks passed!
mypy hyperscaled tests    → Success: no issues found in 40 source files
```

### Warning observed

`pytest` still reports one existing runtime warning in `tests/test_client.py`:

- `TestSyncHelpers.test_run_sync_raises_in_running_loop`
- warning: `coroutine 'sleep' was never awaited`

This warning predates the hardening work and does not block the branch, but it may be worth cleaning up separately.

---

## Why This Was Done Before SDK-005

These changes reduce rework on the next ticket:

- **Correctness:** `SDK-005` is the first real API integration and depends on stable base URL resolution
- **Local dev reliability:** imports and tests now behave better before or outside a package install step
- **Documentation accuracy:** the public repo docs now match the actual implemented surface area

---

## Next Step

Proceed to `SDK-005` after confirming the miner API contract for:

- endpoint paths
- response shape and field names
- optional/null fields
- error responses
- pricing and account-size data types
