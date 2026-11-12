"""Strategy interface + shared context.

Strategies only BUILD entries (OrderIntent) and declare TP/SL params. Exit
monitoring (TP / SL / time square-off) is centralised in the engine so every
structure is managed consistently and defined-risk is always enforced.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Optional

from bot.models import Candle, ChainSnapshot, OrderIntent, RegimeDecision


@dataclass
class StrategyContext:
    now_ms: int
    chain: ChainSnapshot
    candles_5m: list[Candle]
    candles_15m: list[Candle]
    regime: Optional[RegimeDecision]
    is_expiry: bool
    vix: float
    iv_rank: float
    lot_size: int
    num_lots: int = 1              # user-configured lots; leg qty = lot_size * num_lots


class Strategy(abc.ABC):
    kind: str = "BASE"

    def __init__(self, cfg) -> None:
        self.cfg = cfg

    @abc.abstractmethod
    def build_entry(self, ctx: StrategyContext) -> Optional[OrderIntent]:
        """Return an OrderIntent to open, or None to stay flat this cycle."""
        ...
