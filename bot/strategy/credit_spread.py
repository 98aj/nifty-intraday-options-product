"""Small defined-risk credit spread for RANGE + high-IV days.

Sell a short option near the configured delta on the side away from the slight
bias, buy a protective wing. Small size, tight wings. TP at a fraction of credit;
SL at a multiple of credit.
"""
from __future__ import annotations

from typing import Optional

from bot.models import (Leg, OptionType, OrderIntent, Side, StrategyKind)
from bot.strategy.base import Strategy, StrategyContext
from bot.strategy import strikes


class CreditSpread(Strategy):
    kind = StrategyKind.CREDIT_SPREAD

    def build_entry(self, ctx: StrategyContext) -> Optional[OrderIntent]:
        c = self.cfg.strategy.credit_spread
        chain = ctx.chain
        step = self.cfg.instrument.strike_step

        # Range: sell the side opposite the last bias; default to PE (bullish-ish)
        bias = ctx.regime.bias if ctx.regime else "NEUTRAL"
        opt = OptionType.CE if bias == "DOWN" else OptionType.PE

        short_q = strikes.nearest_by_delta(chain, opt, c.short_delta_target)
        if short_q is None:
            short_q = strikes.by_offset(chain, opt, step,
                                        c.fallback_short_offset_steps)
        if short_q is None:
            return None
        long_q = strikes.wing_strike(chain, short_q.strike, opt, c.wing_width_points)
        if long_q is None:
            return None

        credit_pts = short_q.mid - long_q.mid
        if credit_pts <= 0:
            return None
        qty = ctx.lot_size * ctx.num_lots
        max_reward = credit_pts * qty
        max_risk = (c.wing_width_points - credit_pts) * qty
        legs = [
            Leg(long_q.instrument_key, f"{opt.value}{int(long_q.strike)}", opt,
                long_q.strike, Side.BUY, qty, entry_price=long_q.mid),
            Leg(short_q.instrument_key, f"{opt.value}{int(short_q.strike)}", opt,
                short_q.strike, Side.SELL, qty, entry_price=short_q.mid),
        ]
        return OrderIntent(
            kind=StrategyKind.CREDIT_SPREAD, legs=legs, expiry=chain.expiry,
            max_risk=max_risk, max_reward=max_reward, credit=credit_pts * qty,
            reason=(f"range credit spread: short {int(short_q.strike)}{opt.value} / "
                    f"long {int(long_q.strike)}{opt.value}, credit {credit_pts:.1f}pts "
                    f"(IV-rank {ctx.iv_rank:.0f})"),
            tag="credit_spread",
        )
