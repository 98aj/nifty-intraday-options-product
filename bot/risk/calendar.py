"""Trading-calendar helpers: holidays and event blackout days (no new entries)."""
from __future__ import annotations

import datetime as dt


class TradingCalendar:
    def __init__(self, cfg) -> None:
        self.holidays = set(cfg.calendar.holidays)
        self.blackouts = set(cfg.calendar.event_blackout_dates)

    def is_holiday(self, d: dt.date) -> bool:
        return d.isoformat() in self.holidays or d.weekday() >= 5

    def is_blackout(self, d: dt.date) -> bool:
        return d.isoformat() in self.blackouts
