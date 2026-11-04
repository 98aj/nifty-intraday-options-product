"""Compute take-profit / stop-loss pnl levels for a built intent.

Centralised so paper + (future) live executors and the engine agree on exits.
Levels are absolute rupee pnl thresholds on the position (gross of exit costs).
"""
from __future__ import annotations

from bot.models import OrderIntent, StrategyKind


def compute_exit_levels(cfg, intent: OrderIntent) -> tuple[float, float, float]:
    """Return (take_profit_level, stop_loss_level, take_profit_pct)."""
    k = intent.kind
    if k == StrategyKind.IRON_CONDOR:
        c = cfg.strategy.iron_condor
        credit = intent.credit                      # > 0
        return (c.take_profit_pct * credit, -c.stop_loss_mult * credit,
                c.take_profit_pct)
    if k == StrategyKind.CREDIT_SPREAD:
        c = cfg.strategy.credit_spread
        credit = intent.credit
        return (c.take_profit_pct * credit, -c.stop_loss_mult * credit,
                c.take_profit_pct)
    if k == StrategyKind.DEBIT_SPREAD:
        c = cfg.strategy.debit_spread
        debit = -intent.credit                      # credit stored negative
        tp = c.take_profit_pct * intent.max_reward
        sl = -c.stop_loss_pct * debit
        return (tp, sl, c.take_profit_pct)
    return (0.0, 0.0, 0.0)
