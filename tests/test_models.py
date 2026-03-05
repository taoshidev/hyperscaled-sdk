"""Tests for all Pydantic models (SDK-004)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from hyperscaled.models import (
    AccountInfo,
    ClosedPosition,
    EntityMiner,
    LeverageLimits,
    Order,
    Payout,
    Position,
    PricingTier,
    ProfitSplit,
    RegistrationStatus,
    Rule,
    RuleViolation,
    TradeValidation,
)

# ── Fixtures ─────────────────────────────────────────────


def _now() -> datetime:
    return datetime(2026, 3, 5, 12, 0, 0, tzinfo=timezone.utc)


def _pricing_tier() -> PricingTier:
    return PricingTier(account_size=50_000, cost=Decimal("250.00"))


def _profit_split() -> ProfitSplit:
    return ProfitSplit(trader_pct=80, miner_pct=20)


def _entity_miner() -> EntityMiner:
    return EntityMiner(
        name="Vanta Trading",
        slug="vantatrading",
        url="https://vantatrading.com",
        pricing_tiers=[
            PricingTier(account_size=25_000, cost=Decimal("150.00")),
            PricingTier(account_size=50_000, cost=Decimal("250.00")),
        ],
        profit_split=_profit_split(),
        payout_cadence="weekly",
        supported_pairs=["BTC-USDC", "ETH-USDC", "SOL-USDC"],
        leverage_limits={"BTC": 50.0, "ETH": 50.0, "SOL": 20.0},
        available_account_sizes=[25_000, 50_000, 100_000],
    )


def _leverage_limits() -> LeverageLimits:
    return LeverageLimits(
        account_level=20.0,
        position_level={"BTC": 50.0, "ETH": 50.0},
    )


# ── PricingTier ──────────────────────────────────────────


class TestPricingTier:
    def test_valid(self) -> None:
        tier = _pricing_tier()
        assert tier.account_size == 50_000
        assert tier.cost == Decimal("250.00")

    def test_json_roundtrip(self) -> None:
        tier = _pricing_tier()
        data = json.loads(tier.model_dump_json())
        restored = PricingTier.model_validate(data)
        assert restored == tier


# ── ProfitSplit ──────────────────────────────────────────


class TestProfitSplit:
    def test_valid(self) -> None:
        split = _profit_split()
        assert split.trader_pct == 80
        assert split.miner_pct == 20

    def test_json_roundtrip(self) -> None:
        split = _profit_split()
        data = json.loads(split.model_dump_json())
        restored = ProfitSplit.model_validate(data)
        assert restored == split


# ── EntityMiner ──────────────────────────────────────────


class TestEntityMiner:
    def test_valid(self) -> None:
        miner = _entity_miner()
        assert miner.slug == "vantatrading"
        assert len(miner.pricing_tiers) == 2
        assert miner.profit_split.trader_pct == 80
        assert miner.leverage_limits["BTC"] == 50.0

    def test_optional_url_defaults_to_none(self) -> None:
        miner = EntityMiner(
            name="Test",
            slug="test",
            pricing_tiers=[],
            profit_split=_profit_split(),
            payout_cadence="weekly",
            supported_pairs=[],
            leverage_limits={},
            available_account_sizes=[],
        )
        assert miner.url is None

    def test_json_roundtrip(self) -> None:
        miner = _entity_miner()
        data = json.loads(miner.model_dump_json())
        restored = EntityMiner.model_validate(data)
        assert restored == miner


# ── Order ────────────────────────────────────────────────


class TestOrder:
    def test_valid_market_order(self) -> None:
        order = Order(
            hl_order_id="abc123",
            pair="BTC-USDC",
            side="long",
            size=Decimal("200"),
            funded_equivalent_size=Decimal("20000"),
            order_type="market",
            status="filled",
            fill_price=Decimal("100250.50"),
            scaling_ratio=Decimal("100"),
            created_at=_now(),
        )
        assert order.side == "long"
        assert order.fill_price == Decimal("100250.50")
        assert order.take_profit is None
        assert order.stop_loss is None

    def test_invalid_side_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Order(
                hl_order_id="x",
                pair="BTC-USDC",
                side="up",  # type: ignore[arg-type]
                size=Decimal("1"),
                funded_equivalent_size=Decimal("1"),
                order_type="market",
                status="filled",
                scaling_ratio=Decimal("1"),
                created_at=_now(),
            )

    def test_json_roundtrip(self) -> None:
        order = Order(
            hl_order_id="abc123",
            pair="ETH-USDC",
            side="short",
            size=Decimal("100"),
            funded_equivalent_size=Decimal("10000"),
            order_type="limit",
            status="pending",
            scaling_ratio=Decimal("100"),
            take_profit=Decimal("3000"),
            stop_loss=Decimal("4000"),
            created_at=_now(),
        )
        data = json.loads(order.model_dump_json())
        restored = Order.model_validate(data)
        assert restored == order


# ── Position / ClosedPosition ────────────────────────────


class TestPosition:
    def test_valid(self) -> None:
        pos = Position(
            symbol="BTC-USDC",
            side="long",
            size=Decimal("200"),
            position_value=Decimal("20000"),
            entry_price=Decimal("100000"),
            mark_price=Decimal("101000"),
            unrealized_pnl=Decimal("200"),
            open_time=_now(),
        )
        assert pos.liquidation_price is None
        assert pos.unrealized_pnl == Decimal("200")

    def test_json_roundtrip(self) -> None:
        pos = Position(
            symbol="ETH-USDC",
            side="short",
            size=Decimal("50"),
            position_value=Decimal("5000"),
            entry_price=Decimal("3500"),
            mark_price=Decimal("3400"),
            liquidation_price=Decimal("4000"),
            unrealized_pnl=Decimal("100"),
            open_time=_now(),
        )
        data = json.loads(pos.model_dump_json())
        restored = Position.model_validate(data)
        assert restored == pos


class TestClosedPosition:
    def test_extends_position(self) -> None:
        closed = ClosedPosition(
            symbol="BTC-USDC",
            side="long",
            size=Decimal("200"),
            position_value=Decimal("20000"),
            entry_price=Decimal("100000"),
            mark_price=Decimal("101000"),
            unrealized_pnl=Decimal("0"),
            open_time=_now(),
            realized_pnl=Decimal("500"),
            close_time=_now(),
        )
        assert isinstance(closed, Position)
        assert closed.realized_pnl == Decimal("500")

    def test_json_roundtrip(self) -> None:
        closed = ClosedPosition(
            symbol="SOL-USDC",
            side="short",
            size=Decimal("10"),
            position_value=Decimal("1000"),
            entry_price=Decimal("150"),
            mark_price=Decimal("140"),
            unrealized_pnl=Decimal("0"),
            open_time=_now(),
            realized_pnl=Decimal("100"),
            close_time=_now(),
        )
        data = json.loads(closed.model_dump_json())
        restored = ClosedPosition.model_validate(data)
        assert restored == closed


# ── LeverageLimits / AccountInfo ─────────────────────────


class TestLeverageLimits:
    def test_valid(self) -> None:
        ll = _leverage_limits()
        assert ll.account_level == 20.0
        assert ll.position_level["BTC"] == 50.0

    def test_json_roundtrip(self) -> None:
        ll = _leverage_limits()
        data = json.loads(ll.model_dump_json())
        restored = LeverageLimits.model_validate(data)
        assert restored == ll


class TestAccountInfo:
    def test_valid(self) -> None:
        info = AccountInfo(
            status="active",
            funded_account_size=100_000,
            hl_wallet_address="0x" + "a" * 40,
            payout_wallet_address="0x" + "b" * 40,
            entity_miner="vantatrading",
            current_drawdown=Decimal("-3.5"),
            max_drawdown_limit=Decimal("-10"),
            leverage_limits=_leverage_limits(),
            hl_balance=Decimal("5000"),
            funded_balance=Decimal("100000"),
            kyc_status="verified",
        )
        assert info.status == "active"
        assert info.funded_account_size == 100_000
        assert info.kyc_status == "verified"

    def test_invalid_status_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AccountInfo(
                status="deleted",  # type: ignore[arg-type]
                funded_account_size=100_000,
                hl_wallet_address="0x" + "a" * 40,
                payout_wallet_address="0x" + "b" * 40,
                entity_miner="vantatrading",
                current_drawdown=Decimal("0"),
                max_drawdown_limit=Decimal("-10"),
                leverage_limits=_leverage_limits(),
                hl_balance=Decimal("5000"),
                funded_balance=Decimal("100000"),
                kyc_status="verified",
            )

    def test_json_roundtrip(self) -> None:
        info = AccountInfo(
            status="suspended",
            funded_account_size=50_000,
            hl_wallet_address="0x" + "c" * 40,
            payout_wallet_address="0x" + "d" * 40,
            entity_miner="alphaquant",
            current_drawdown=Decimal("-8"),
            max_drawdown_limit=Decimal("-10"),
            leverage_limits=_leverage_limits(),
            hl_balance=Decimal("2000"),
            funded_balance=Decimal("50000"),
            kyc_status="not_started",
        )
        data = json.loads(info.model_dump_json())
        restored = AccountInfo.model_validate(data)
        assert restored == info


# ── Payout ───────────────────────────────────────────────


class TestPayout:
    def test_valid(self) -> None:
        payout = Payout(
            date=_now(),
            amount=Decimal("1250.00"),
            token="USDC",
            network="arbitrum",
            tx_hash="0xabc123",
            status="completed",
        )
        assert payout.token == "USDC"
        assert payout.status == "completed"

    def test_optional_tx_hash(self) -> None:
        payout = Payout(
            date=_now(),
            amount=Decimal("500"),
            token="USDC",
            network="arbitrum",
            status="pending",
        )
        assert payout.tx_hash is None

    def test_json_roundtrip(self) -> None:
        payout = Payout(
            date=_now(),
            amount=Decimal("1250.00"),
            token="USDC",
            network="arbitrum",
            status="processing",
        )
        data = json.loads(payout.model_dump_json())
        restored = Payout.model_validate(data)
        assert restored == payout


# ── RegistrationStatus ───────────────────────────────────


class TestRegistrationStatus:
    def test_valid_pending(self) -> None:
        reg = RegistrationStatus(
            status="pending",
            registration_id="reg-001",
            account_size=100_000,
            estimated_time="~30s",
        )
        assert reg.funded_account_id is None
        assert reg.estimated_time == "~30s"

    def test_valid_registered(self) -> None:
        reg = RegistrationStatus(
            status="registered",
            registration_id="reg-001",
            funded_account_id="fa-001",
            account_size=100_000,
        )
        assert reg.funded_account_id == "fa-001"

    def test_json_roundtrip(self) -> None:
        reg = RegistrationStatus(
            status="failed",
            registration_id="reg-002",
            account_size=50_000,
        )
        data = json.loads(reg.model_dump_json())
        restored = RegistrationStatus.model_validate(data)
        assert restored == reg


# ── Rule / RuleViolation / TradeValidation ───────────────


class TestRule:
    def test_valid(self) -> None:
        rule = Rule(
            rule_id="PAIR_RESTRICTION_001",
            category="pairs",
            description="Only BTC, ETH, SOL, XRP, DOGE, ADA pairs allowed",
            limit="6 pairs",
            applies_to="all accounts",
        )
        assert rule.current_value is None
        assert rule.category == "pairs"

    def test_invalid_category_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Rule(
                rule_id="X",
                category="unknown",  # type: ignore[arg-type]
                description="bad",
                limit="0",
            )

    def test_json_roundtrip(self) -> None:
        rule = Rule(
            rule_id="LEVERAGE_001",
            category="leverage",
            description="Max account leverage 20x",
            current_value="15x",
            limit="20x",
        )
        data = json.loads(rule.model_dump_json())
        restored = Rule.model_validate(data)
        assert restored == rule


class TestRuleViolation:
    def test_valid(self) -> None:
        rule = Rule(
            rule_id="LEVERAGE_001",
            category="leverage",
            description="Max leverage 20x",
            limit="20x",
        )
        violation = RuleViolation(
            rule=rule,
            actual_value="25x",
            message="Leverage 25x exceeds maximum 20x",
        )
        assert violation.rule.rule_id == "LEVERAGE_001"
        assert violation.actual_value == "25x"


class TestTradeValidation:
    def test_valid_trade(self) -> None:
        result = TradeValidation(valid=True, violations=[])
        assert result.valid is True
        assert result.violations == []

    def test_invalid_trade_with_violations(self) -> None:
        rule = Rule(
            rule_id="PAIR_RESTRICTION_001",
            category="pairs",
            description="Restricted pairs",
            limit="6 pairs",
        )
        violation = RuleViolation(
            rule=rule,
            actual_value="LINK-USDC",
            message="LINK-USDC is not a supported pair",
        )
        result = TradeValidation(valid=False, violations=[violation])
        assert result.valid is False
        assert len(result.violations) == 1

    def test_json_roundtrip(self) -> None:
        result = TradeValidation(valid=True, violations=[])
        data = json.loads(result.model_dump_json())
        restored = TradeValidation.model_validate(data)
        assert restored == result
