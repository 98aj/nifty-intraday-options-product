"""Transaction-cost model (brokerage + STT + exchange txn + GST + stamp + SEBI).

Used both to estimate round-trip cost before entry (cost-awareness gate) and to
charge realistic costs on paper fills.
"""
from __future__ import annotations

from bot.models import OrderIntent, Side


def leg_premium_turnover(price: float, qty: int) -> float:
    return price * qty


def estimate_entry_costs(cfg, intent: OrderIntent) -> float:
    """Approximate ENTRY-side charges for all legs of an intent."""
    c = cfg.costs
    brokerage = c.brokerage_per_order * len(intent.legs)
    stt = exch = stamp = 0.0
    sell_turn = buy_turn = 0.0
    for leg in intent.legs:
        turn = leg_premium_turnover(leg.entry_price, leg.qty)
        if leg.side == Side.SELL:
            sell_turn += turn
        else:
            buy_turn += turn
    stt = sell_turn * c.stt_pct_sell_premium / 100.0
    exch = (sell_turn + buy_turn) * c.exchange_txn_pct / 100.0
    stamp = buy_turn * c.stamp_pct_buy / 100.0
    sebi = (sell_turn + buy_turn) * c.sebi_per_crore / 1e7
    gst = (brokerage + exch + sebi) * c.gst_pct / 100.0
    return brokerage + stt + exch + stamp + sebi + gst


def estimate_round_trip_costs(cfg, intent: OrderIntent) -> float:
    """Entry + exit (~2x entry as a conservative round-trip estimate)."""
    return 2.0 * estimate_entry_costs(cfg, intent)


def fill_cost_for_leg(cfg, price: float, qty: int, side: Side) -> float:
    c = cfg.costs
    brokerage = c.brokerage_per_order
    turn = leg_premium_turnover(price, qty)
    stt = turn * c.stt_pct_sell_premium / 100.0 if side == Side.SELL else 0.0
    exch = turn * c.exchange_txn_pct / 100.0
    stamp = turn * c.stamp_pct_buy / 100.0 if side == Side.BUY else 0.0
    sebi = turn * c.sebi_per_crore / 1e7
    gst = (brokerage + exch + sebi) * c.gst_pct / 100.0
    return brokerage + stt + exch + stamp + sebi + gst
