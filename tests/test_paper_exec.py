from bot.execution.paper import PaperExecutor
from bot.models import (ChainSnapshot, Leg, OptionQuote, OptionType, OrderIntent,
                        Side, StrategyKind)


def _chain():
    def q(strike, ot, px):
        return OptionQuote(expiry="2026-11-10", strike=strike, opt_type=ot,
                           instrument_key=f"{int(strike)}{ot.value}", ltp=px,
                           bid=px - 1, ask=px + 1)
    quotes = [
        q(24300, OptionType.CE, 20),
        q(23700, OptionType.PE, 20),
        q(24200, OptionType.CE, 50),
        q(23800, OptionType.PE, 50),
    ]
    return ChainSnapshot(ts_ms=0, spot=24000, vix=12, expiry="2026-11-10",
                         quotes=quotes)


def _intent(qty=75):
    legs = [
        Leg("24300CE", "CE24300", OptionType.CE, 24300, Side.BUY, qty),
        Leg("23700PE", "PE23700", OptionType.PE, 23700, Side.BUY, qty),
        Leg("24200CE", "CE24200", OptionType.CE, 24200, Side.SELL, qty),
        Leg("23800PE", "PE23800", OptionType.PE, 23800, Side.SELL, qty),
    ]
    return OrderIntent(StrategyKind.IRON_CONDOR, legs, "2026-11-10",
                       max_risk=40 * qty, max_reward=60 * qty, credit=60 * qty)


def test_open_fills_longs_before_shorts(cfg):
    ex = PaperExecutor(cfg)
    order = []
    orig = ex._fill_price

    def spy(chain, leg, closing):
        order.append((leg.side, closing))
        return orig(chain, leg, closing)

    ex._fill_price = spy
    pos = ex.open_position(_intent(), _chain(), ts_ms=1000)
    # all BUY (longs) must be filled before any SELL (short)
    sides = [s for s, _ in order]
    first_sell = sides.index(Side.SELL)
    assert all(s == Side.BUY for s in sides[:first_sell])
    assert pos.entry_net > 0  # net credit structure
    assert pos.open is True


def test_close_buys_back_shorts_before_longs(cfg):
    ex = PaperExecutor(cfg)
    pos = ex.open_position(_intent(), _chain(), ts_ms=1000)
    order = []
    orig = ex._fill_price

    def spy(chain, leg, closing):
        order.append(leg.side)
        return orig(chain, leg, closing)

    ex._fill_price = spy
    realized = ex.close_position(pos, _chain(), ts_ms=2000, reason="test")
    # shorts (SELL legs) are bought back FIRST, longs removed LAST
    first_long = order.index(Side.BUY)
    assert all(s == Side.SELL for s in order[:first_long])
    assert pos.open is False
    assert isinstance(realized, float)
