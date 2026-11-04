"""Position sizing from capital + max-risk-per-trade %, scaled down when VIX is
high. Phase 1 trades a single lot; sizing returns a lot multiplier (>=0) and the
engine keeps max_open_positions = 1, so this mainly gates/scales the base lot.
"""
from __future__ import annotations

import math


def vix_scale(vix: float, spike_pct: float) -> float:
    """1.0 in calm vol, shrinking toward 0.5 as VIX rises past the spike level."""
    if vix <= spike_pct:
        return 1.0
    over = (vix - spike_pct) / spike_pct
    return max(0.5, 1.0 - 0.5 * min(1.0, over))


def lots_for_trade(cfg, max_risk_per_lot: float, vix: float) -> int:
    """How many lots keep per-trade risk within the capital budget."""
    if max_risk_per_lot <= 0:
        return 0
    budget = cfg.capital.total * cfg.capital.max_risk_per_trade_pct / 100.0
    budget *= vix_scale(vix, cfg.regime.vix_spike_pct)
    lots = math.floor(budget / max_risk_per_lot)
    return max(0, lots)
