"""Strike-selection helpers over a ChainSnapshot."""
from __future__ import annotations

from typing import Optional

from bot.models import ChainSnapshot, OptionQuote, OptionType


def atm_strike(chain: ChainSnapshot, step: int) -> float:
    return round(chain.spot / step) * step


def nearest_by_delta(chain: ChainSnapshot, opt: OptionType,
                     target_abs_delta: float) -> Optional[OptionQuote]:
    """Pick the strike whose |delta| is closest to target (needs greeks).

    Falls back to None if no quote carries a delta (e.g. live greeks missing).
    """
    best: Optional[OptionQuote] = None
    best_err = 1e9
    for q in chain.quotes:
        if q.opt_type != opt or q.delta is None:
            continue
        err = abs(abs(q.delta) - target_abs_delta)
        if err < best_err:
            best_err = err
            best = q
    return best


def by_offset(chain: ChainSnapshot, opt: OptionType, step: int,
              steps_from_atm: int) -> Optional[OptionQuote]:
    atm = atm_strike(chain, step)
    sign = 1 if opt == OptionType.CE else -1
    strike = atm + sign * steps_from_atm * step
    return chain.get(strike, opt)


def by_strike(chain: ChainSnapshot, strike: float, opt: OptionType) -> Optional[OptionQuote]:
    return chain.get(strike, opt)


def wing_strike(chain: ChainSnapshot, short_strike: float, opt: OptionType,
                wing_width: int) -> Optional[OptionQuote]:
    """Protective long leg `wing_width` points further OTM than the short."""
    sign = 1 if opt == OptionType.CE else -1
    strike = short_strike + sign * wing_width
    return chain.get(strike, opt)
