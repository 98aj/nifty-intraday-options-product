"""Directional debit spread for TREND days.

Buy ~ATM, sell ~OTM in the trend direction, triggered by a 5-min breakout that
agrees with the 15-min trend. Defined risk = debit paid. TP at a fraction of max
profit; SL at a fraction of debit.
"""
from __future__ import annotations

from typing import Optional

from bot.models import (Leg, OptionType, OrderIntent, Regime, Side, StrategyKind)
from bot.strategy.base import Strategy, StrategyContext
from bot.strategy import strikes


class DebitSpread(Strategy):
    kind = StrategyKind.DEBIT_SPREAD

    def _breakout_direction(self, ctx: StrategyContext) -> Optional[str]:
        """5-min breakout over the recent range -> 'UP' or 'DOWN', else None."""
        bars = ctx.candles_5m
        look = self.cfg.strategy.breakout_lookback_bars
        if len(bars) < look + 1:
            return None
        window = bars[-(look + 1):-1]
        hi = max(b.high for b in window)
        lo = min(b.low for b in window)
        last = bars[-1]
        if last.close > hi:
            return "UP"
        if last.close < lo:
            return "DOWN"
        return None

    def build_entry(self, ctx: StrategyContext) -> Optional[OrderIntent]:
        reg = ctx.regime
        if reg is None or reg.regime not in (Regime.TREND_UP, Regime.TREND_DOWN):
            return None
        trend_dir = "UP" if reg.regime == Regime.TREND_UP else "DOWN"
        brk = self._breakout_direction(ctx)
        if brk is None or brk != trend_dir:        # timeframes must agree
            return None

        c = self.cfg.strategy.debit_spread
        step = self.cfg.instrument.strike_step
        chain = ctx.chain
        opt = OptionType.CE if trend_dir == "UP" else OptionType.PE

        long_q = strikes.by_offset(chain, opt, step, c.long_offset_steps)
        short_q = strikes.by_offset(chain, opt, step, c.short_offset_steps)
        if long_q is None or short_q is None:
            return None

        debit_pts = long_q.mid - short_q.mid
        if debit_pts <= 0:
            return None
        width = abs(short_q.strike - long_q.strike)
        qty = ctx.lot_size
        max_risk = debit_pts * qty
        max_reward = (width - debit_pts) * qty
        legs = [
            Leg(long_q.instrument_key, f"{opt.value}{int(long_q.strike)}", opt,
                long_q.strike, Side.BUY, qty, entry_price=long_q.mid),
            Leg(short_q.instrument_key, f"{opt.value}{int(short_q.strike)}", opt,
                short_q.strike, Side.SELL, qty, entry_price=short_q.mid),
        ]
        return OrderIntent(
            kind=StrategyKind.DEBIT_SPREAD, legs=legs, expiry=chain.expiry,
            max_risk=max_risk, max_reward=max_reward, credit=-debit_pts * qty,
            reason=(f"{trend_dir} debit spread: long {int(long_q.strike)}{opt.value} / "
                    f"short {int(short_q.strike)}{opt.value}, debit {debit_pts:.1f}pts "
                    f"(ADX {reg.adx:.0f}, 5m breakout)"),
            tag="debit_spread",
        )
