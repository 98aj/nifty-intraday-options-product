"""Iron condor for expiry-day premium selling (0DTE pin play).

Short CE + short PE near the configured delta, each protected by a long wing
`wing_width_points` further OTM (defined risk — never a naked short leg). Enter
only if India VIX is below a threshold. TP at a fraction of credit; SL at a
multiple of credit (both enforced centrally by the engine).
"""
from __future__ import annotations

from typing import Optional

from bot.models import (Leg, OptionType, OrderIntent, Side, StrategyKind)
from bot.strategy.base import Strategy, StrategyContext
from bot.strategy import strikes


class IronCondor(Strategy):
    kind = StrategyKind.IRON_CONDOR

    def build_entry(self, ctx: StrategyContext) -> Optional[OrderIntent]:
        c = self.cfg.strategy.iron_condor
        if ctx.vix > c.max_vix_to_enter:
            return None
        chain = ctx.chain
        step = self.cfg.instrument.strike_step

        short_ce = strikes.nearest_by_delta(chain, OptionType.CE, c.short_delta_target)
        short_pe = strikes.nearest_by_delta(chain, OptionType.PE, c.short_delta_target)
        if short_ce is None or short_pe is None:
            # greeks unavailable -> fall back to a fixed offset
            short_ce = strikes.by_offset(chain, OptionType.CE, step,
                                         c.fallback_short_offset_steps)
            short_pe = strikes.by_offset(chain, OptionType.PE, step,
                                         c.fallback_short_offset_steps)
        if short_ce is None or short_pe is None:
            return None

        long_ce = strikes.wing_strike(chain, short_ce.strike, OptionType.CE,
                                      c.wing_width_points)
        long_pe = strikes.wing_strike(chain, short_pe.strike, OptionType.PE,
                                      c.wing_width_points)
        if long_ce is None or long_pe is None:
            return None

        credit_pts = (short_ce.mid + short_pe.mid) - (long_ce.mid + long_pe.mid)
        if credit_pts < c.min_credit_points:
            return None

        qty = ctx.lot_size
        legs = [
            Leg(long_ce.instrument_key, f"CE{int(long_ce.strike)}", OptionType.CE,
                long_ce.strike, Side.BUY, qty, entry_price=long_ce.mid),
            Leg(long_pe.instrument_key, f"PE{int(long_pe.strike)}", OptionType.PE,
                long_pe.strike, Side.BUY, qty, entry_price=long_pe.mid),
            Leg(short_ce.instrument_key, f"CE{int(short_ce.strike)}", OptionType.CE,
                short_ce.strike, Side.SELL, qty, entry_price=short_ce.mid),
            Leg(short_pe.instrument_key, f"PE{int(short_pe.strike)}", OptionType.PE,
                short_pe.strike, Side.SELL, qty, entry_price=short_pe.mid),
        ]
        wing = c.wing_width_points
        max_reward = credit_pts * qty
        max_risk = (wing - credit_pts) * qty
        return OrderIntent(
            kind=StrategyKind.IRON_CONDOR, legs=legs, expiry=chain.expiry,
            max_risk=max_risk, max_reward=max_reward, credit=credit_pts * qty,
            reason=(f"expiry condor: SCE {int(short_ce.strike)} / SPE "
                    f"{int(short_pe.strike)}, credit {credit_pts:.1f}pts"),
            tag="iron_condor",
        )
