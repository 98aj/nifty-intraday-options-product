from bot.models import Regime
from bot.regime.regime_engine import RegimeEngine


def test_no_immediate_flip(cfg):
    cfg.regime.confirmations_required = 2
    cfg.regime.min_dwell_bars = 2
    eng = RegimeEngine(cfg)
    # first commit from UNKNOWN is allowed
    eng._committed = Regime.RANGE
    eng._bars_in_regime = 5
    # one opposing read should NOT switch (needs 2 confirmations)
    out = eng._apply_hysteresis(Regime.TREND_UP, conf=0.9)
    assert out == Regime.RANGE
    # second confirmation switches
    out = eng._apply_hysteresis(Regime.TREND_UP, conf=0.9)
    assert out == Regime.TREND_UP


def test_dwell_blocks_switch(cfg):
    cfg.regime.confirmations_required = 1
    cfg.regime.min_dwell_bars = 3
    eng = RegimeEngine(cfg)
    eng._committed = Regime.RANGE
    eng._bars_in_regime = 1  # not enough dwell
    out = eng._apply_hysteresis(Regime.TREND_DOWN, conf=0.9)
    assert out == Regime.RANGE  # dwell not satisfied


def test_low_confidence_blocks_switch(cfg):
    cfg.regime.confirmations_required = 1
    cfg.regime.min_dwell_bars = 1
    cfg.regime.confidence_min = 0.55
    eng = RegimeEngine(cfg)
    eng._committed = Regime.RANGE
    eng._bars_in_regime = 5
    out = eng._apply_hysteresis(Regime.TREND_UP, conf=0.40)
    assert out == Regime.RANGE
