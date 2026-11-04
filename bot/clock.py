"""Time utilities: IST timezone, session windows, and a simulated clock.

Everything the engine times against goes through a Clock, so simulate mode can
accelerate wall time without changing any downstream logic.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime, date, time as dtime, timedelta

import pytz

IST = pytz.timezone("Asia/Kolkata")
UTC = pytz.UTC


def now_ist() -> datetime:
    return datetime.now(IST)


def to_ist(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = UTC.localize(dt)
    return dt.astimezone(IST)


def epoch_ms(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = IST.localize(dt)
    return int(dt.timestamp() * 1000)


def ist_str(dt: datetime) -> str:
    return to_ist(dt).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def parse_hhmm(s: str) -> dtime:
    h, m = s.split(":")
    return dtime(int(h), int(m))


@dataclass
class SessionWindow:
    open: dtime
    close: dtime
    no_new_entry_after: dtime
    hard_squareoff: dtime
    expiry_squareoff: dtime


class Clock:
    """Real-time clock. `now()` returns tz-aware IST datetime."""

    def __init__(self) -> None:
        self._offset = timedelta(0)

    def now(self) -> datetime:
        return now_ist() + self._offset

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    @property
    def is_sim(self) -> bool:
        return False


class SimClock(Clock):
    """Accelerated clock for simulate mode.

    Starts at a chosen IST datetime (today's market open by default) and advances
    `speed_factor` sim-seconds per real second. Threads call `sleep()` which maps
    sim-duration to a (much shorter) real sleep.
    """

    def __init__(self, start: datetime, speed_factor: float = 60.0) -> None:
        super().__init__()
        self._speed = max(1.0, float(speed_factor))
        self._start_real = time.monotonic()
        if start.tzinfo is None:
            start = IST.localize(start)
        self._start_sim = start.astimezone(IST)
        self._lock = threading.Lock()

    def now(self) -> datetime:
        with self._lock:
            elapsed_real = time.monotonic() - self._start_real
            return self._start_sim + timedelta(seconds=elapsed_real * self._speed)

    def sleep(self, seconds: float) -> None:
        # Sleep in sim-seconds -> compress to real time.
        time.sleep(max(0.0, seconds / self._speed))

    @property
    def is_sim(self) -> bool:
        return True


def build_session_window(session_cfg) -> SessionWindow:
    return SessionWindow(
        open=parse_hhmm(session_cfg.market_open),
        close=parse_hhmm(session_cfg.market_close),
        no_new_entry_after=parse_hhmm(session_cfg.no_new_entry_after),
        hard_squareoff=parse_hhmm(session_cfg.hard_squareoff),
        expiry_squareoff=parse_hhmm(session_cfg.expiry_squareoff),
    )


def session_open_dt(d: date) -> datetime:
    return IST.localize(datetime.combine(d, dtime(9, 15)))


def session_close_dt(d: date) -> datetime:
    return IST.localize(datetime.combine(d, dtime(15, 30)))


def squareoff_time(win: SessionWindow, is_expiry: bool) -> dtime:
    return win.expiry_squareoff if is_expiry else win.hard_squareoff


def within_live_window(win: SessionWindow, now: datetime,
                       lead_minutes: int = 15) -> bool:
    """True if `now` (IST) is inside the window we allow contacting Upstox: from
    `lead_minutes` before the open (for warm-up / WS connect) through the close.
    After the close this is False, so live mode never calls Upstox after hours."""
    t = now.time()
    open_lead = (datetime.combine(now.date(), win.open)
                 - timedelta(minutes=lead_minutes)).time()
    return open_lead <= t <= win.close
