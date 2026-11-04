"""Top-level DAY SWITCH router.

- Expiry day (derived from the contract list, NOT a fixed weekday) -> iron condor.
- Normal day, regime-driven:
    TREND            -> directional debit spread
    RANGE + IV high  -> small credit spread
    RANGE + IV normal/low, or TRANSITION / UNKNOWN / low confidence -> FLAT
"""
from __future__ import annotations

from typing import Optional

from bot.models import OrderIntent, Regime, StrategyKind
from bot.strategy.base import Strategy, StrategyContext
from bot.strategy.credit_spread import CreditSpread
from bot.strategy.debit_spread import DebitSpread
from bot.strategy.iron_condor import IronCondor


class DaySwitch:
    def __init__(self, cfg) -> None:
        self.cfg = cfg
        self.iron_condor = IronCondor(cfg)
        self.debit_spread = DebitSpread(cfg)
        self.credit_spread = CreditSpread(cfg)

    def decide_kind(self, ctx: StrategyContext) -> tuple[StrategyKind, str]:
        if ctx.is_expiry:
            return StrategyKind.IRON_CONDOR, "expiry day -> premium selling (condor)"
        reg = ctx.regime
        if reg is None:
            return StrategyKind.FLAT, "regime warming up -> flat"
        if reg.confidence < self.cfg.regime.confidence_min:
            return StrategyKind.FLAT, f"low confidence {reg.confidence:.2f} -> flat"
        if reg.regime in (Regime.TREND_UP, Regime.TREND_DOWN):
            return StrategyKind.DEBIT_SPREAD, "trend -> directional debit spread"
        if reg.regime == Regime.RANGE:
            if ctx.iv_rank >= self.cfg.iv_rank.high_threshold:
                return StrategyKind.CREDIT_SPREAD, (
                    f"range + IV-rank {ctx.iv_rank:.0f} high -> credit spread")
            return StrategyKind.FLAT, (
                f"range + IV-rank {ctx.iv_rank:.0f} normal/low -> flat")
        return StrategyKind.FLAT, f"{reg.regime.value} -> flat"

    def build_entry(self, ctx: StrategyContext) -> tuple[StrategyKind, str,
                                                         Optional[OrderIntent]]:
        kind, reason = self.decide_kind(ctx)
        strat: Optional[Strategy] = {
            StrategyKind.IRON_CONDOR: self.iron_condor,
            StrategyKind.DEBIT_SPREAD: self.debit_spread,
            StrategyKind.CREDIT_SPREAD: self.credit_spread,
        }.get(kind)
        if strat is None:
            return kind, reason, None
        return kind, reason, strat.build_entry(ctx)
