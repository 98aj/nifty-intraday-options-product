"""Backend-agnostic storage interface.

The recorder and engine depend only on Repository, so swapping SQLite -> another
backend (or adding Parquet-direct) is additive, not a rewrite. All writes are
routed through a single writer (the recorder thread) and batched.
"""
from __future__ import annotations

import abc
from typing import Sequence

from bot.models import Candle, ChainSnapshot, RegimeDecision, Tick


class Repository(abc.ABC):
    @abc.abstractmethod
    def open_day(self, day: str) -> None:
        """Open / create the storage for trading day YYYY-MM-DD."""

    @abc.abstractmethod
    def insert_ticks(self, ticks: Sequence[Tick]) -> int: ...

    @abc.abstractmethod
    def insert_chain(self, snap: ChainSnapshot) -> int: ...

    @abc.abstractmethod
    def insert_candle(self, candle: Candle) -> None: ...

    @abc.abstractmethod
    def insert_regime(self, decision: RegimeDecision) -> None: ...

    @abc.abstractmethod
    def insert_journal(self, event: str, kind: str, approved,
                       pnl, detail: str, payload: dict, ts_ms: int) -> None: ...

    @abc.abstractmethod
    def counts(self) -> dict: ...

    @abc.abstractmethod
    def flush(self) -> None: ...

    @abc.abstractmethod
    def close(self) -> None: ...

    @property
    @abc.abstractmethod
    def db_path(self) -> str: ...
