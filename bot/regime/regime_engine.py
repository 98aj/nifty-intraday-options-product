"""Regime engine: multi-factor vote -> confidence, with confirmation + dwell
hysteresis so the regime can't flip-flop. Every decision is logged with its factor
values and a human-readable reason (transparent, not a black box).

Factors: ADX level + slope, Choppiness Index, India VIX context.
15-min candles drive this (regime + bias). Entry trigger (5-min) is handled by the
strategy, which only acts when the two timeframes agree.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from bot.models import Candle, Regime, RegimeDecision
from bot.regime import indicators as ind


class RegimeEngine:
    def __init__(self, cfg) -> None:
        self.cfg = cfg.regime
        self._committed: Regime = Regime.UNKNOWN
        self._pending: Optional[Regime] = None
        self._pending_count = 0
        self._bars_in_regime = 0

    def _vote(self, adx_v: float, adx_slope: float, chop_v: float,
              vix: float, last_close: float, prev_close: float
              ) -> tuple[Regime, float, str, str]:
        c = self.cfg
        reasons = []
        bias = "NEUTRAL"

        trend_votes = 0.0
        range_votes = 0.0
        total = 3.0

        # ADX factor
        if adx_v >= c.adx_trend_min:
            trend_votes += 1.0
            reasons.append(f"ADX {adx_v:.1f}>= {c.adx_trend_min} trend")
        else:
            range_votes += 1.0
            reasons.append(f"ADX {adx_v:.1f}< {c.adx_trend_min} range")

        # ADX slope (rising strengthens trend conviction)
        if adx_slope > 0 and adx_v >= c.adx_trend_min:
            reasons.append(f"ADX slope +{adx_slope:.2f}")

        # Choppiness factor
        if chop_v <= c.chop_trend_max:
            trend_votes += 1.0
            reasons.append(f"CHOP {chop_v:.1f}<= {c.chop_trend_max} trend")
        elif chop_v >= c.chop_range_min:
            range_votes += 1.0
            reasons.append(f"CHOP {chop_v:.1f}>= {c.chop_range_min} range")
        else:
            reasons.append(f"CHOP {chop_v:.1f} neutral")

        # VIX context factor: a spiking VIX discourages committing to trend
        if vix >= c.vix_spike_pct:
            range_votes += 0.5
            total += 0.0
            reasons.append(f"VIX {vix:.1f} elevated -> caution")
        else:
            trend_votes += 0.0

        # Decide direction bias from last bar move
        if last_close > prev_close:
            bias = "UP"
        elif last_close < prev_close:
            bias = "DOWN"

        if trend_votes > range_votes:
            raw = Regime.TREND_UP if bias == "UP" else (
                Regime.TREND_DOWN if bias == "DOWN" else Regime.TRANSITION)
            conf = min(1.0, trend_votes / total)
        elif range_votes > trend_votes:
            raw = Regime.RANGE
            conf = min(1.0, range_votes / total)
        else:
            raw = Regime.TRANSITION
            conf = 0.4

        return raw, conf, bias, "; ".join(reasons)

    def update(self, candles_15m: list[Candle], vix: float) -> Optional[RegimeDecision]:
        """Call on each closed 15m bar. Returns a RegimeDecision (always logged)."""
        n_needed = self.cfg.adx_period * 2
        if len(candles_15m) < n_needed:
            return None

        highs = np.array([c.high for c in candles_15m])
        lows = np.array([c.low for c in candles_15m])
        closes = np.array([c.close for c in candles_15m])

        adx_arr = ind.adx(highs, lows, closes, self.cfg.adx_period)
        chop_arr = ind.choppiness(highs, lows, closes, self.cfg.chop_period)
        adx_v = float(np.nan_to_num(adx_arr[-1]))
        chop_v = float(np.nan_to_num(chop_arr[-1], nan=50.0))
        adx_slope = ind.slope(adx_arr, self.cfg.adx_slope_lookback)

        raw, conf, bias, reason = self._vote(
            adx_v, adx_slope, chop_v, vix, closes[-1], closes[-2])

        committed = self._apply_hysteresis(raw, conf)
        ts_ms = candles_15m[-1].end_ms

        final_conf = conf if committed == raw else max(0.4, conf * 0.8)
        if final_conf < self.cfg.confidence_min and committed != Regime.RANGE:
            note = f" | low-conf {final_conf:.2f}<{self.cfg.confidence_min} -> FLAT bias"
        else:
            note = ""

        return RegimeDecision(
            ts_ms=ts_ms, regime=committed, confidence=round(final_conf, 3),
            adx=round(adx_v, 2), adx_slope=round(adx_slope, 3),
            chop=round(chop_v, 2), vix=round(vix, 2), bias=bias,
            reason=reason + note, raw_regime=raw,
        )

    def _apply_hysteresis(self, raw: Regime, conf: float) -> Regime:
        c = self.cfg
        self._bars_in_regime += 1

        if raw == self._committed:
            self._pending = None
            self._pending_count = 0
            return self._committed

        # a different reading: require N confirmations AND min dwell before switch
        if self._pending == raw:
            self._pending_count += 1
        else:
            self._pending = raw
            self._pending_count = 1

        can_switch = (self._pending_count >= c.confirmations_required
                      and self._bars_in_regime >= c.min_dwell_bars
                      and conf >= c.confidence_min)
        if can_switch or self._committed == Regime.UNKNOWN:
            self._committed = raw
            self._bars_in_regime = 0
            self._pending = None
            self._pending_count = 0
        return self._committed

    @property
    def committed(self) -> Regime:
        return self._committed
