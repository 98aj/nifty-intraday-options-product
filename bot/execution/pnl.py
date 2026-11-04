"""Mark-to-market helpers shared by the engine and executors."""
from __future__ import annotations

from typing import Optional

from bot.models import ChainSnapshot, Position, Side


def _leg_mark(chain: ChainSnapshot, leg) -> Optional[float]:
    q = chain.get(leg.strike, leg.opt_type)
    if q is None:
        return None
    return q.mid


def gross_pnl(pos: Position, chain: ChainSnapshot) -> float:
    """Gross pnl (rupees) if marked at current chain mids. None marks -> skip leg
    (keeps its contribution at 0, i.e. last-known entry)."""
    total = 0.0
    for leg in pos.legs:
        mark = _leg_mark(chain, leg)
        if mark is None:
            continue
        if leg.side == Side.SELL:
            total += (leg.entry_price - mark) * leg.qty
        else:
            total += (mark - leg.entry_price) * leg.qty
    return total


def unrealized_pnl(pos: Position, chain: ChainSnapshot) -> float:
    """Gross mark pnl minus entry costs already paid."""
    return gross_pnl(pos, chain) - pos.entry_costs
