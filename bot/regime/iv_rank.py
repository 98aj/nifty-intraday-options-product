"""IV-rank provider.

v1 uses India VIX percentile over a lookback (we have no per-strike IV history
yet). Once our own chain snapshots cover enough days, switch source to chain_iv.

- sim: returns a configured constant.
- live vix_percentile: pulls India VIX daily history from Upstox and computes the
  percentile of the latest close; on any failure returns a neutral 50.
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import requests

from bot.data.upstox_auth import API_BASE, default_headers


class IVRankProvider:
    def __init__(self, cfg) -> None:
        self.cfg = cfg
        self._value = 50.0

    def warm(self) -> float:
        if self.cfg.simulate_feed:
            self._value = float(self.cfg.sim.iv_rank_value)
            return self._value
        if self.cfg.iv_rank.source == "vix_percentile":
            self._value = self._vix_percentile()
        return self._value

    def current(self) -> float:
        return self._value

    def _vix_percentile(self) -> float:
        try:
            token = self.cfg.secrets.upstox_access_token
            end = dt.date.today()
            start = end - dt.timedelta(days=self.cfg.iv_rank.lookback_days + 30)
            key = self.cfg.instrument.vix_key.replace("|", "%7C")
            url = (f"{API_BASE}/v2/historical-candle/{key}/day/"
                   f"{end.isoformat()}/{start.isoformat()}")
            r = requests.get(url, headers=default_headers(token), timeout=15)
            r.raise_for_status()
            candles = r.json().get("data", {}).get("candles", [])
            closes = [row[4] for row in candles if len(row) > 4]
            if len(closes) < 20:
                return 50.0
            arr = np.array(closes, dtype=float)
            latest = arr[0]            # Upstox returns newest-first
            pct = float((arr < latest).mean() * 100.0)
            return round(pct, 2)
        except Exception:
            return 50.0
