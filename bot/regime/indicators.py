"""Indicators: ADX (+slope) and Choppiness Index.

Prefers pandas-ta when available; always provides a dependency-free fallback so the
regime engine runs even if pandas-ta can't be imported (common on Windows/py3.12).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np

try:  # optional
    import pandas as pd
    import pandas_ta as pta  # noqa: F401
    _HAS_PTA = True
except Exception:  # pragma: no cover
    _HAS_PTA = False


@dataclass
class OHLC:
    high: Sequence[float]
    low: Sequence[float]
    close: Sequence[float]


def _wilder_rma(values: np.ndarray, period: int) -> np.ndarray:
    """Wilder's smoothing (RMA)."""
    out = np.full_like(values, np.nan, dtype=float)
    if len(values) < period:
        return out
    out[period - 1] = values[:period].mean()
    alpha = 1.0 / period
    for i in range(period, len(values)):
        out[i] = out[i - 1] + alpha * (values[i] - out[i - 1])
    return out


def adx_fallback(high, low, close, period: int = 14) -> np.ndarray:
    high = np.asarray(high, dtype=float)
    low = np.asarray(low, dtype=float)
    close = np.asarray(close, dtype=float)
    n = len(close)
    adx = np.full(n, np.nan)
    if n < period * 2:
        return adx

    up = high[1:] - high[:-1]
    dn = low[:-1] - low[1:]
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)

    tr = np.maximum.reduce([
        high[1:] - low[1:],
        np.abs(high[1:] - close[:-1]),
        np.abs(low[1:] - close[:-1]),
    ])

    atr = _wilder_rma(tr, period)
    plus_di = 100.0 * _wilder_rma(plus_dm, period) / np.where(atr == 0, np.nan, atr)
    minus_di = 100.0 * _wilder_rma(minus_dm, period) / np.where(atr == 0, np.nan, atr)
    dx = 100.0 * np.abs(plus_di - minus_di) / np.where(
        (plus_di + minus_di) == 0, np.nan, (plus_di + minus_di))
    adx_vals = _wilder_rma(np.nan_to_num(dx), period)
    # align back to full length (shifted by 1 due to diff)
    adx[1:] = adx_vals
    return adx


def adx(high, low, close, period: int = 14) -> np.ndarray:
    if _HAS_PTA:
        try:
            df = pd.DataFrame({"high": high, "low": low, "close": close})
            res = df.ta.adx(length=period)
            col = f"ADX_{period}"
            if res is not None and col in res:
                return res[col].to_numpy(dtype=float)
        except Exception:
            pass
    return adx_fallback(high, low, close, period)


def choppiness(high, low, close, period: int = 14) -> np.ndarray:
    high = np.asarray(high, dtype=float)
    low = np.asarray(low, dtype=float)
    close = np.asarray(close, dtype=float)
    n = len(close)
    chop = np.full(n, np.nan)
    if n < period + 1:
        return chop
    tr = np.maximum.reduce([
        high[1:] - low[1:],
        np.abs(high[1:] - close[:-1]),
        np.abs(low[1:] - close[:-1]),
    ])
    tr = np.concatenate([[np.nan], tr])
    log_p = np.log10(period)
    for i in range(period, n):
        atr_sum = np.nansum(tr[i - period + 1:i + 1])
        hh = np.max(high[i - period + 1:i + 1])
        ll = np.min(low[i - period + 1:i + 1])
        rng = hh - ll
        if rng <= 0 or atr_sum <= 0:
            continue
        chop[i] = 100.0 * np.log10(atr_sum / rng) / log_p
    return chop


def slope(values: np.ndarray, lookback: int) -> float:
    """Simple slope of the last `lookback` non-nan points."""
    vals = values[~np.isnan(values)]
    if len(vals) < lookback + 1:
        return 0.0
    y = vals[-(lookback + 1):]
    x = np.arange(len(y))
    try:
        m = np.polyfit(x, y, 1)[0]
    except Exception:
        m = 0.0
    return float(m)
