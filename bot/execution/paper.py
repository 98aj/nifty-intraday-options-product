"""PaperExecutor: pessimistic paper fills with correct leg ordering.

ENTER: place protective (long) legs FIRST, then the shorts.
EXIT : close the shorts FIRST, then remove the protective longs LAST.
This guarantees the book is never (even briefly) net-naked in simulation, matching
how the live executor must behave.

Fills: BUY at ask + slippage, SELL at bid - slippage (pessimistic). Costs charged
per leg via the cost model.
"""
from __future__ import annotations

from bot.execution.base import ExecutorBase
from bot.execution.pnl import gross_pnl
from bot.models import (ChainSnapshot, Leg, OrderIntent, Position, Side)
from bot.risk import costs as cost_model
from bot.strategy.exits import compute_exit_levels


class PaperExecutor(ExecutorBase):
    def __init__(self, cfg) -> None:
        super().__init__(cfg)
        self.slip = cfg.costs.slippage_points_per_leg

    def _fill_price(self, chain: ChainSnapshot, leg: Leg, closing: bool) -> float:
        q = chain.get(leg.strike, leg.opt_type)
        ref_bid = q.bid if (q and q.bid) else (q.ltp if q else leg.entry_price)
        ref_ask = q.ask if (q and q.ask) else (q.ltp if q else leg.entry_price)
        # effective action: opening uses leg.side; closing reverses it
        action_buy = (leg.side == Side.BUY) ^ closing
        if action_buy:
            return max(0.05, ref_ask + self.slip)
        return max(0.05, ref_bid - self.slip)

    def open_position(self, intent: OrderIntent, chain: ChainSnapshot,
                      ts_ms: int) -> Position:
        longs = [l for l in intent.legs if l.side == Side.BUY]
        shorts = [l for l in intent.legs if l.side == Side.SELL]
        entry_net = 0.0
        entry_costs = 0.0
        # longs FIRST (protection on before any short is sold)
        for leg in longs + shorts:
            px = self._fill_price(chain, leg, closing=False)
            leg.entry_price = px
            entry_costs += cost_model.fill_cost_for_leg(
                self.cfg, px, leg.qty, leg.side)
            if leg.side == Side.SELL:
                entry_net += px * leg.qty
            else:
                entry_net -= px * leg.qty

        tp, sl, tp_pct = compute_exit_levels(self.cfg, intent)
        return Position(
            kind=intent.kind, legs=intent.legs, expiry=intent.expiry,
            entry_ts_ms=ts_ms, entry_net=entry_net,
            max_risk=intent.max_risk, max_reward=intent.max_reward,
            take_profit_pct=tp_pct, stop_loss_level=sl, take_profit_level=tp,
            tag=intent.tag, entry_costs=entry_costs, open=True,
        )

    def close_position(self, pos: Position, chain: ChainSnapshot,
                       ts_ms: int, reason: str) -> float:
        longs = [l for l in pos.legs if l.side == Side.BUY]
        shorts = [l for l in pos.legs if l.side == Side.SELL]
        exit_costs = 0.0
        # shorts FIRST (buy them back), longs LAST (remove protection last)
        for leg in shorts + longs:
            px = self._fill_price(chain, leg, closing=True)
            leg.exit_price = px
            # closing side is the reverse of the open side for cost purposes
            close_side = Side.BUY if leg.side == Side.SELL else Side.SELL
            exit_costs += cost_model.fill_cost_for_leg(
                self.cfg, px, leg.qty, close_side)

        gross = 0.0
        for leg in pos.legs:
            if leg.side == Side.SELL:
                gross += (leg.entry_price - leg.exit_price) * leg.qty
            else:
                gross += (leg.exit_price - leg.entry_price) * leg.qty

        realized = gross - pos.entry_costs - exit_costs
        pos.open = False
        pos.exit_ts_ms = ts_ms
        pos.exit_reason = reason
        pos.realized = realized
        pos.current_net = 0.0
        pos.pnl = realized
        return realized
