import numpy as np

from bot.regime import indicators as ind


def _trend_series(n=80):
    close = np.linspace(100, 200, n)
    high = close + 1.0
    low = close - 1.0
    return high, low, close


def _range_series(n=80):
    x = np.arange(n)
    close = 100 + 2.0 * np.sin(x / 3.0)
    high = close + 1.0
    low = close - 1.0
    return high, low, close


def test_adx_fallback_trend_high():
    h, l, c = _trend_series()
    adx = ind.adx_fallback(h, l, c, 14)
    assert np.nanmax(adx) > 25  # strong trend => high ADX


def test_adx_matches_shape():
    h, l, c = _trend_series()
    adx = ind.adx(h, l, c, 14)
    assert len(adx) == len(c)


def test_choppiness_range_high():
    h, l, c = _range_series()
    chop = ind.choppiness(h, l, c, 14)
    assert np.nanmean(chop[20:]) > 50  # choppy/range => high CHOP


def test_slope_positive_on_rising():
    vals = np.array([np.nan, np.nan, 10, 12, 14, 16.0])
    assert ind.slope(vals, 3) > 0
