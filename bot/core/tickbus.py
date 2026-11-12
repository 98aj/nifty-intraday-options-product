"""TickBus: one feed thread fans ticks out to per-consumer queues.

The feed thread must NEVER block on a slow consumer. Each subscriber gets its own
bounded queue; if a queue is full the tick is dropped for that subscriber and a
counter is incremented (surfaced as an alert), but trading for other instruments
and recording are unaffected.
"""
from __future__ import annotations

import queue
import threading
from collections import defaultdict
from typing import Callable, Optional

from bot.models import Tick


class Subscriber:
    def __init__(self, name: str, maxsize: int) -> None:
        self.name = name
        self.q: "queue.Queue[Tick]" = queue.Queue(maxsize=maxsize)
        self.dropped = 0
        # optional instrument filter; None => all
        self.keys: Optional[set[str]] = None


class TickBus:
    def __init__(self) -> None:
        self._subs: list[Subscriber] = []
        self._lock = threading.Lock()
        self.total_published = 0

    def subscribe(self, name: str, maxsize: int = 10000,
                  keys: Optional[set[str]] = None) -> Subscriber:
        sub = Subscriber(name, maxsize)
        sub.keys = keys
        with self._lock:
            self._subs.append(sub)
        return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        """Remove a subscriber (e.g. at end of a trading day) so a long-lived
        bus does not accumulate stale queues across sessions."""
        with self._lock:
            if sub in self._subs:
                self._subs.remove(sub)

    def publish(self, tick: Tick) -> None:
        self.total_published += 1
        # snapshot subscriber list without holding lock during put
        with self._lock:
            subs = list(self._subs)
        for sub in subs:
            if sub.keys is not None and tick.instrument_key not in sub.keys:
                continue
            try:
                sub.q.put_nowait(tick)
            except queue.Full:
                sub.dropped += 1

    def drop_report(self) -> dict[str, int]:
        with self._lock:
            return {s.name: s.dropped for s in self._subs if s.dropped}
