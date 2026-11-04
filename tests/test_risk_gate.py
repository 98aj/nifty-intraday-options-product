import datetime as dt

import pytz

from bot.models import Leg, OptionType, OrderIntent, Side, StrategyKind
from bot.risk.risk_manager import RiskManager

IST = pytz.timezone("Asia/Kolkata")


def _condor(qty=75):
    legs = [
        Leg("LCE", "CE24300", OptionType.CE, 24300, Side.BUY, qty, entry_price=20),
        Leg("LPE", "PE23700", OptionType.PE, 23700, Side.BUY, qty, entry_price=20),
        Leg("SCE", "CE24200", OptionType.CE, 24200, Side.SELL, qty, entry_price=50),
        Leg("SPE", "PE23800", OptionType.PE, 23800, Side.SELL, qty, entry_price=50),
    ]
    credit = (50 + 50 - 20 - 20) * qty
    return OrderIntent(StrategyKind.IRON_CONDOR, legs, "2026-11-10",
                       max_risk=(100 - 60) * qty, max_reward=credit, credit=credit)


def _naked(qty=75):
    legs = [Leg("SCE", "CE24200", OptionType.CE, 24200, Side.SELL, qty, entry_price=50)]
    return OrderIntent(StrategyKind.IRON_CONDOR, legs, "2026-11-10",
                       max_risk=1000, max_reward=50 * qty, credit=50 * qty)


def test_defined_risk_passes(cfg):
    rm = RiskManager(cfg)
    now = IST.localize(dt.datetime(2026, 11, 10, 10, 0))
    d = rm.evaluate(_condor(), now, vix=12.0, is_expiry=True, past_entry_cutoff=False)
    assert d.approved, d.reason


def test_naked_short_rejected(cfg):
    rm = RiskManager(cfg)
    now = IST.localize(dt.datetime(2026, 11, 10, 10, 0))
    d = rm.evaluate(_naked(), now, vix=12.0, is_expiry=True, past_entry_cutoff=False)
    assert not d.approved
    assert "naked" in d.reason.lower()


def test_past_cutoff_rejected(cfg):
    rm = RiskManager(cfg)
    now = IST.localize(dt.datetime(2026, 11, 10, 14, 45))
    d = rm.evaluate(_condor(), now, vix=12.0, is_expiry=True, past_entry_cutoff=True)
    assert not d.approved


def test_daily_halt(cfg):
    rm = RiskManager(cfg)
    cfg.capital.total = 500000
    cfg.capital.daily_max_loss_pct = 3.0
    rm.state.realized_pnl = -16000  # > 15000 loss
    assert rm.check_daily_halt(0.0) is not None


def test_max_trades_blocks(cfg):
    rm = RiskManager(cfg)
    rm.state.trades_today = cfg.capital.max_trades_per_day
    now = IST.localize(dt.datetime(2026, 11, 10, 10, 0))
    d = rm.evaluate(_condor(), now, vix=12.0, is_expiry=True, past_entry_cutoff=False)
    assert not d.approved
