import pytest

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


def _trend_cfg(cfg):
    cfg.regime.adx_trend_min = 22
    cfg.regime.chop_trend_max = 38.2
    cfg.regime.chop_range_min = 61.8
    cfg.regime.vix_spike_pct = 17.0
    cfg.regime.confidence_min = 0.55
    return cfg


def test_vote_strong_trend_clears_gate_with_neutral_chop(cfg):
    """A strong, rising-ADX, calm-VIX trend must clear 0.55 even when CHOP is
    in the neutral band — the case the old fixed-divisor formula capped at 0.33."""
    eng = RegimeEngine(_trend_cfg(cfg))
    # ADX 41 (trend), slope +1 (rising), CHOP 44 (neutral->split), VIX 15 (calm)
    raw, conf, bias, _ = eng._vote(41.0, 1.0, 44.0, 15.0, 100.0, 99.0)
    assert raw == Regime.TREND_UP
    assert bias == "UP"
    # trend = 1.0 + 0.5(chop split) + 0.5(slope) + 0.5(vix) = 2.5 / 3.0
    assert conf == pytest.approx(2.5 / 3.0)
    assert conf >= cfg.regime.confidence_min


def test_vote_strong_adx_fading_slope_still_trends(cfg):
    """A strong ADX with a *maturing* (falling) slope should still trade: the
    falling slope splits its weight rather than vetoing the trend."""
    eng = RegimeEngine(_trend_cfg(cfg))
    # ADX 41 (trend), slope -1 (maturing->split), CHOP 50 (neutral->split), VIX 20 (elevated)
    raw, conf, _, _ = eng._vote(41.0, -1.0, 50.0, 20.0, 100.0, 99.0)
    # trend = 1.0 + 0.5(chop) + 0.25(slope) = 1.75 / 3.0
    assert raw == Regime.TREND_UP
    assert conf == pytest.approx(1.75 / 3.0)
    assert conf >= cfg.regime.confidence_min


def test_vote_weak_adx_stays_range(cfg):
    """Without a real trend (ADX below min), the day must not trade directionally."""
    eng = RegimeEngine(_trend_cfg(cfg))
    # ADX 18 (range), slope -1 (maturing->split), CHOP 50 (neutral->split), VIX 20 (elevated)
    raw, conf, _, _ = eng._vote(18.0, -1.0, 50.0, 20.0, 99.0, 100.0)
    # range = 1.0(adx) + 0.5(chop) + 0.25(slope) + 0.5(vix) = 2.25 / 3.0
    assert raw == Regime.RANGE
    assert conf == pytest.approx(2.25 / 3.0)


def test_vote_choppy_highvix_is_range(cfg):
    eng = RegimeEngine(_trend_cfg(cfg))
    # ADX 18 (range), slope -1 (maturing->split), CHOP 65 (range), VIX 22 (elevated)
    raw, conf, _, _ = eng._vote(18.0, -1.0, 65.0, 22.0, 99.0, 100.0)
    # range = 1.0(adx) + 1.0(chop) + 0.25(slope) + 0.5(vix) = 2.75 / 3.0
    assert raw == Regime.RANGE
    assert conf == pytest.approx(2.75 / 3.0)
