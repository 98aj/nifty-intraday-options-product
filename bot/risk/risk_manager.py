"""Risk manager — the gatekeeper. NOTHING reaches execution without passing here.

Checks (every one logged with pass/reject + reason):
  - defined risk only (no naked short leg; every short has a protective long)
  - max_risk computed and within per-trade budget (VIX-scaled)
  - daily max-loss halt / optional profit-target halt
  - max open positions (1) and max trades/day
  - cost-awareness: expected round-trip cost must not swamp the max reward
  - session timing: no new entries after cutoff / blackout / holiday
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Optional

from bot.models import OptionType, OrderIntent, Side, StrategyKind
from bot.risk import costs as cost_model
from bot.risk.calendar import TradingCalendar
from bot.risk.sizing import vix_scale


@dataclass
class RiskDecision:
    approved: bool
    reason: str
    max_risk: float = 0.0
    max_reward: float = 0.0
    est_costs: float = 0.0
    lots: int = 1


class DayRiskState:
    """Mutable per-day counters the gate reads."""

    def __init__(self) -> None:
        self.realized_pnl = 0.0
        self.trades_today = 0
        self.open_positions = 0
        self.halted = False
        self.halt_reason: Optional[str] = None


class RiskManager:
    def __init__(self, cfg) -> None:
        self.cfg = cfg
        self.calendar = TradingCalendar(cfg)
        self.state = DayRiskState()

    # ---- daily halts (checked continuously, not just at entry) ----
    def check_daily_halt(self, unrealized_pnl: float = 0.0) -> Optional[str]:
        cap = self.cfg.capital
        total_pnl = self.state.realized_pnl + unrealized_pnl
        max_loss = -cap.total * cap.daily_max_loss_pct / 100.0
        if total_pnl <= max_loss:
            return (f"daily max loss hit ({total_pnl:.0f} <= {max_loss:.0f}) "
                    f"-> HALT for the day")
        if cap.daily_profit_target_pct > 0:
            target = cap.total * cap.daily_profit_target_pct / 100.0
            if total_pnl >= target:
                return (f"daily profit target hit ({total_pnl:.0f} >= {target:.0f}) "
                        f"-> HALT for the day")
        return None

    def halt(self, reason: str) -> None:
        self.state.halted = True
        self.state.halt_reason = reason

    # ---- defined-risk structural check ----
    @staticmethod
    def _is_defined_risk(intent: OrderIntent) -> tuple[bool, str]:
        """A short leg is defined-risk iff a long leg of the SAME option type covers
        its quantity. A matched call (or put) vertical is always bounded, regardless
        of which strike is the short — so the check is purely quantity coverage per
        option type (this is what prevents a naked short)."""
        for ot in (OptionType.CE, OptionType.PE):
            short_qty = sum(l.qty for l in intent.legs
                            if l.side == Side.SELL and l.opt_type == ot)
            long_qty = sum(l.qty for l in intent.legs
                           if l.side == Side.BUY and l.opt_type == ot)
            if short_qty > long_qty:
                uncovered = short_qty - long_qty
                return False, (f"naked short {ot.value}: {uncovered} uncovered "
                               f"contracts (short {short_qty} > long {long_qty})")
        return True, "defined risk ok"

    # ---- main gate ----
    def evaluate(self, intent: OrderIntent, now: dt.datetime, vix: float,
                 is_expiry: bool, past_entry_cutoff: bool) -> RiskDecision:
        s = self.state
        if s.halted:
            return RiskDecision(False, f"bot halted: {s.halt_reason}")
        if self.calendar.is_blackout(now.date()):
            return RiskDecision(False, "event blackout day -> no new entries")
        if past_entry_cutoff:
            return RiskDecision(False, "past no-new-entry cutoff")
        if s.open_positions >= self.cfg.capital.max_open_positions:
            return RiskDecision(False, "max open positions reached")
        if s.trades_today >= self.cfg.capital.max_trades_per_day:
            return RiskDecision(False, "max trades/day reached")

        ok, why = self._is_defined_risk(intent)
        if not ok:
            return RiskDecision(False, f"REJECT (risk): {why}")

        if intent.max_risk <= 0:
            return RiskDecision(False, "non-positive max_risk computed")

        # Fixed-lots-win: the legs already carry the user's configured lots
        # (num_lots * lot_size), so intent.max_risk is the TOTAL risk for the
        # position. We do not resize it; we only block if those lots would
        # breach the per-trade budget (capital acts as the brake).
        lots = max(1, int(self.cfg.capital.lots))
        scale = vix_scale(vix, self.cfg.regime.vix_spike_pct)
        budget = (self.cfg.capital.total
                  * self.cfg.capital.max_risk_per_trade_pct / 100.0) * scale
        if intent.max_risk > budget:
            return RiskDecision(
                False,
                f"{lots} lot(s) risk {intent.max_risk:.0f} exceeds per-trade "
                f"budget {budget:.0f} (VIX scale {scale:.2f}) -> reduce lots")

        est = cost_model.estimate_round_trip_costs(self.cfg, intent)
        if intent.max_reward > 0 and est >= 0.5 * intent.max_reward:
            return RiskDecision(
                False,
                f"cost-aware reject: est round-trip {est:.0f} >= 50% of reward "
                f"{intent.max_reward:.0f}")

        return RiskDecision(
            True, f"PASS: {why}; risk {intent.max_risk:.0f}, reward "
                  f"{intent.max_reward:.0f}, est cost {est:.0f}, lots {lots}",
            max_risk=intent.max_risk, max_reward=intent.max_reward,
            est_costs=est, lots=lots,
        )

    # ---- lifecycle updates ----
    def on_open(self) -> None:
        self.state.open_positions += 1
        self.state.trades_today += 1

    def on_close(self, realized: float) -> None:
        self.state.open_positions = max(0, self.state.open_positions - 1)
        self.state.realized_pnl += realized

    def reset_day(self) -> None:
        self.state = DayRiskState()
