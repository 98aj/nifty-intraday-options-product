"""Inbound command plumbing shared by Telegram and the FastAPI webhook.

Commands are enqueued (thread-safe) and drained by the engine's control loop so an
external caller can never execute engine logic directly on its own thread.
"""
from __future__ import annotations

import queue
import time
from dataclasses import dataclass
from enum import Enum


class CommandType(str, Enum):
    STATUS = "status"
    PAUSE = "pause"
    RESUME = "resume"
    FLATTEN = "flatten"
    KILL = "kill"
    RECORD_ON = "record_on"      # start persisting ticks + chain snapshots
    RECORD_OFF = "record_off"    # stop persisting ticks + chain (journal keeps logging)
    MODE_PAPER = "mode_paper"    # switch execution to paper (simulated fills)
    MODE_LIVE = "mode_live"      # switch execution to live (Phase 1: refused, safe)


VALID_COMMANDS = {c.value for c in CommandType}


@dataclass
class Command:
    type: CommandType
    source: str               # "telegram" | "api"
    ts_ms: int
    reply: "queue.Queue | None" = None   # optional sync reply channel


class CommandQueue:
    def __init__(self, maxsize: int = 1000) -> None:
        self._q: "queue.Queue[Command]" = queue.Queue(maxsize=maxsize)

    def submit(self, type_: CommandType, source: str,
               reply: "queue.Queue | None" = None) -> None:
        self._q.put(Command(type_, source, int(time.time() * 1000), reply))

    def get(self, timeout: float = 0.2):
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None
