"""StateStore: lock-guarded shared state returning immutable snapshots.

Readers (UI, snapshot writer, command handlers) call `snapshot()` which copies
under a short-held lock and returns a plain dict. Readers never hold the lock long
enough to stall a trading thread, and they never get a live reference into engine
state.
"""
from __future__ import annotations

import copy
import threading
import time
from typing import Any


class StateStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: dict[str, Any] = {
            "status": "STARTING",
            "mode": "paper",
            "simulate_feed": False,
            "updated_ms": int(time.time() * 1000),
            "session_date": None,
            "is_expiry_day": False,
            "underlying": {"symbol": "NIFTY", "ltp": 0.0, "ts_ms": 0},
            "vix": 0.0,
            "regime": None,
            "strategy_today": None,
            "position": None,
            "pnl_day": 0.0,
            "realized_pnl_day": 0.0,
            "trades_today": 0,
            "halted_reason": None,
            "candles_5m": [],      # recent closed candles (trimmed)
            "candles_15m": [],
            "recorder": {"ticks": 0, "chain_snaps": 0, "dropped": 0,
                         "queue_depth": 0, "db_file": None, "collecting": False},
            "last_signal": None,
            "journal_tail": [],    # recent journal lines
            "trades": [],          # closed trades today (table on the dashboard)
            "config": {},          # user-editable settings (capital, lot, risk)
            "warnings": [],
        }

    def update(self, **kwargs) -> None:
        with self._lock:
            self._state.update(kwargs)
            self._state["updated_ms"] = int(time.time() * 1000)

    def set_path(self, key: str, value: Any) -> None:
        with self._lock:
            self._state[key] = value
            self._state["updated_ms"] = int(time.time() * 1000)

    def merge(self, key: str, value: dict) -> None:
        with self._lock:
            cur = self._state.get(key)
            if isinstance(cur, dict):
                cur.update(value)
            else:
                self._state[key] = value
            self._state["updated_ms"] = int(time.time() * 1000)

    def push_journal(self, line: str, keep: int = 50) -> None:
        with self._lock:
            tail = self._state["journal_tail"]
            tail.append(line)
            del tail[:-keep]
            self._state["updated_ms"] = int(time.time() * 1000)

    def push_trade(self, trade: dict, keep: int = 100) -> None:
        with self._lock:
            trades = self._state["trades"]
            trades.append(trade)
            del trades[:-keep]
            self._state["updated_ms"] = int(time.time() * 1000)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._state)
