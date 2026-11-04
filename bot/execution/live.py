"""LiveExecutor — DELIBERATELY NOT IMPLEMENTED in Phase 1.

Every entry point raises NotImplementedError so no half-built live order can ever
reach the broker until this is implemented on purpose. Live orders also require the
account's static IP and a daily OAuth token (see upstox_auth).
"""
from __future__ import annotations

from bot.execution.base import ExecutorBase
from bot.models import ChainSnapshot, OrderIntent, Position


class LiveExecutor(ExecutorBase):
    def open_position(self, intent: OrderIntent, chain: ChainSnapshot,
                      ts_ms: int) -> Position:
        # TODO(live): place multi-leg order (longs first), poll fills, build Position.
        raise NotImplementedError(
            "LiveExecutor.open_position is not implemented in Phase 1. "
            "Set mode: paper. Live orders need static IP + daily OAuth token.")

    def close_position(self, pos: Position, chain: ChainSnapshot,
                       ts_ms: int, reason: str) -> float:
        # TODO(live): square off (shorts first, longs last), confirm, return pnl.
        raise NotImplementedError(
            "LiveExecutor.close_position is not implemented in Phase 1.")
