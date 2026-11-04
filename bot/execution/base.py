"""Executor interface + fill records."""
from __future__ import annotations

import abc
from dataclasses import dataclass

from bot.models import ChainSnapshot, OrderIntent, Position


@dataclass
class Fill:
    instrument_key: str
    side: str
    qty: int
    price: float
    cost: float
    ts_ms: int


class ExecutorBase(abc.ABC):
    def __init__(self, cfg) -> None:
        self.cfg = cfg

    @abc.abstractmethod
    def open_position(self, intent: OrderIntent, chain: ChainSnapshot,
                      ts_ms: int) -> Position: ...

    @abc.abstractmethod
    def close_position(self, pos: Position, chain: ChainSnapshot,
                       ts_ms: int, reason: str) -> float:
        """Close all legs; return realized pnl (net of costs)."""
        ...
