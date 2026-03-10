# Hyperscaled — Project Overview

## What Is Hyperscaled?

Hyperscaled is an agent-first developer platform for funded trading on Hyperliquid.

Its Phase 1 job is to let developers and agents:
- discover funded account providers
- register for funded accounts
- connect a Hyperliquid wallet
- submit trades governed by Vanta Network rules
- monitor account state, orders, positions, and payouts

Its longer-term job is broader than funded trading alone. Based on the V2 CLI/SDK design, Hyperscaled is evolving into a platform that combines:
- a CLI and Python SDK
- provider discovery
- research and backtesting workflows
- live funded trading
- strategy manifests
- provider monetization and settlement

In other words, Hyperscaled should be understood as a developer interface and coordination layer around Vanta-enforced funded trading, not just a landing page or browser extension.

---

## Core Roles

| Component | Role |
|-----------|------|
| **Hyperscaled** | Developer platform coordinating discovery, registration, research-to-live workflows, and future provider monetization |
| **Vanta Network** | Enforcement and funded-account logic layer for rules, eligibility, drawdown, exposure, and payout behavior |
| **Hyperliquid** | Execution venue where trades are placed |
| **Entity miner** | A funded account provider exposed through Hyperscaled |
| **Provider** | A data, indicator, or function source that can eventually be discovered, composed, and monetized through Hyperscaled |

---

## Product Direction

The V2 design sets the platform roadmap across four major phases:

1. **Funded account registration and trading** via CLI/SDK
2. **Data access and backtesting** for research-to-live continuity
3. **Provider directory and monetization** with free research/challenge usage and funded-only charging
4. **Composable strategy manifests and settlement** for multi-provider strategies

This is an important shift from the older framing. The Chrome extension is still useful, but it is now one interface into the system, not the product definition.

---

## Repositories In This Workspace

### 1. `hyperscaled` — Web Surface and Early Hyperscaled API

**Stack:** Next.js, React, TypeScript

This repo is currently the public web surface for Hyperscaled and also contains the early miner catalog API consumed by the SDK.

**Current responsibilities:**
- public-facing landing page and messaging
- early API routes for miner discovery
- entity miner catalog serialization and tier exposure

**Current API surface:**
- `app/api/v1/miners/route.js` — list miner catalog entries
- `app/api/v1/miners/[slug]/route.js` — fetch one miner by slug
- `lib/miners.js` — loads, normalizes, and serializes miner catalog data

### 2. `hyperscaled-sdk` — CLI and Python SDK

**Stack:** Python, `httpx`, `pydantic`, CLI tooling

This is the main developer interface described by the V2 design. It is the programmatic entry point for agents, scripts, notebooks, and automation.

**Current responsibilities:**
- local config management
- `HyperscaledClient` lifecycle and HTTP client setup
- entity miner discovery against the Hyperscaled API
- CLI entry points for SDK workflows

**Current implementation status:**
- miner discovery is implemented
- several later sub-clients are stubbed for future sprints/phases
- the SDK already assumes `https://api.hyperscaled.com` as the default API base URL

### 3. `hyperscaled_extension` — Browser Trading Enforcer

**Stack:** Chrome Extension (Manifest V3), JavaScript

This repo provides a browser-native trading experience inside Hyperliquid. It visually enforces challenge rules and surfaces account context directly in the Hyperliquid UI.

**Current responsibilities:**
- wallet binding
- balance gating
- pair restrictions
- position limit warnings
- on-page challenge/status overlays
- browser notifications

**Current limitations:**
- challenge progress and drawdown UI still depend on demo or hardcoded values in places
- integration with the broader Hyperscaled platform is still partial

### 4. `vanta-network` — Rule Engine and Funded Trading Infrastructure

**Stack:** Python, Bittensor, Flask/FastAPI

This is the enforcement and funded-account logic layer. It validates rules, tracks performance, manages challenge state, and exposes validator/miner APIs that other Hyperscaled surfaces depend on.

**Core responsibilities:**
- rule enforcement
- position and order tracking
- challenge and funded-state monitoring
- performance and ledger calculation
- payout-related state
- validator, miner, and websocket APIs

**Relevant APIs:**

| API | Port | Purpose |
|-----|------|---------|
| Validator REST | 48888 | Positions, statistics, ledgers, checkpoints, eliminations, entity data |
| Miner REST | 8088 | Order submission, subaccount creation, order status |
| WebSocket | 8765 | Real-time order and position broadcasts |

---

## How The Pieces Fit Together

### Current state

Today, the platform is only partially integrated:

| From → To | Integration | Current state |
|-----------|-------------|---------------|
| `hyperscaled-sdk` → `hyperscaled` | Miner catalog API | Working |
| `hyperscaled-sdk` → `vanta-network` | Direct funded trading flows | Mostly planned / partial |
| `hyperscaled_extension` → Hyperliquid | UI overlays and account checks | Working |
| `hyperscaled_extension` → `vanta-network` | Real challenge/account state | Partial; not yet the full product path |
| `hyperscaled` web → full platform onboarding | Landing and messaging | Early |

### Target architecture aligned with V2

The intended platform now looks like this:

```
Agents / Developers
        ↓
Hyperscaled CLI & SDK
        ↓
Hyperscaled platform services
  • miner / provider discovery
  • registration workflows
  • account state and payouts
  • research and backtesting workflows
  • manifests and settlement over time
        ↓
Vanta Network
  • rules
  • challenge / funded state
  • drawdown and exposure logic
        ↓
Hyperliquid
  • execution venue
```

The browser extension fits alongside this as an optional user-facing client, not as the main architectural center.

---

## Key Alignment Notes

`planning/Hyperscaled CLI & SDK Design V2.md` changes the project framing in a few important ways:

- Hyperscaled is now primarily a **developer platform**, not just a funded-trading front end
- the **CLI and SDK are first-class product surfaces**, not side tooling
- **provider discovery** becomes a core part of the product
- **research-to-live continuity** is part of the intended architecture
- provider pricing is expected to be **free in research and challenge**, then activated only in funded trading
- **strategy manifests and settlement** are part of the long-term design, even if implementation starts lightweight

This overview should therefore be read as both:
- the current repo map
- the V2-aligned system picture the repos are moving toward

---

## Tech Stack Summary

| Repo | Language | Framework / Runtime | Deployment shape |
|------|----------|---------------------|------------------|
| `hyperscaled` | TypeScript | Next.js, React | Web app and early API surface |
| `hyperscaled-sdk` | Python | SDK + CLI | Local developer tool / PyPI package |
| `hyperscaled_extension` | JavaScript | Chrome Extension MV3 | Browser extension |
| `vanta-network` | Python | Bittensor, Flask/FastAPI | Backend / subnet infrastructure |
