"""Data Recorder — independent writer thread.

Consumes from its own deep queue and persists ticks, option-chain snapshots,
candles, regime decisions and journal events into the daily SQLite file. It runs
for the ENTIRE session whenever the feed is live, regardless of whether the
strategy is trading (records even when FLAT).

Design guarantees:
  - Trading never stalls recording and recording never stalls trading: producers
    only `put_nowait` onto a bounded queue; on overflow a drop counter increments
    (surfaced as an alert) rather than blocking a trading thread.
  - High write throughput via batched inserts flushed every `batch_flush_ms` or
    `batch_flush_rows`, one transaction per batch (never per row).
"""
from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

from bot.models import Candle, ChainSnapshot, RegimeDecision, Tick
from bot.storage.repository import Repository


# record envelope types pushed onto the queue
TICK = "tick"
CHAIN = "chain"
CANDLE = "candle"
REGIME = "regime"
JOURNAL = "journal"


@dataclass
class Rec:
    kind: str
    payload: Any


class Recorder:
    def __init__(self, cfg, repo: Repository, state_store=None,
                 notifier=None, enabled: bool = True) -> None:
        self.cfg = cfg
        self.repo = repo
        self.state = state_store
        self.notifier = notifier
        self.q: "queue.Queue[Rec]" = queue.Queue(maxsize=cfg.recorder.queue_maxsize)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.dropped = 0
        self._pending_ticks = 0
        # Runtime toggle for the HIGH-VOLUME market data (ticks + chain snapshots).
        # Candles, regime log and the journal are ALWAYS recorded (audit trail).
        self._collecting = threading.Event()
        if enabled:
            self._collecting.set()

    # ---- collection toggle ----
    def enable(self) -> None:
        self._collecting.set()
        self._publish_counts()

    def disable(self) -> None:
        self._collecting.clear()
        self._publish_counts()

    def is_collecting(self) -> bool:
        return self._collecting.is_set()

    # ---- producer-side API (called from any thread; never blocks) ----
    def _offer(self, rec: Rec) -> None:
        try:
            self.q.put_nowait(rec)
        except queue.Full:
            self.dropped += 1

    def record_tick(self, tick: Tick) -> None:
        if not self._collecting.is_set():
            return                       # collection paused -> drop silently
        self._offer(Rec(TICK, tick))

    def record_chain(self, snap: ChainSnapshot) -> None:
        if not self._collecting.is_set():
            return
        self._offer(Rec(CHAIN, snap))

    def record_candle(self, candle: Candle) -> None:
        self._offer(Rec(CANDLE, candle))

    def record_regime(self, decision: RegimeDecision) -> None:
        self._offer(Rec(REGIME, decision))

    def record_journal(self, event: str, kind: str, approved, pnl,
                       detail: str, payload: dict, ts_ms: int) -> None:
        self._offer(Rec(JOURNAL, {
            "event": event, "kind": kind, "approved": approved, "pnl": pnl,
            "detail": detail, "payload": payload, "ts_ms": ts_ms}))

    # ---- lifecycle ----
    def start(self, day: str) -> None:
        self.repo.open_day(day)
        self._thread = threading.Thread(target=self._run, name="Recorder",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5.0)
        self.repo.close()

    def _run(self) -> None:
        last_flush = time.monotonic()
        batch_rows = 0
        flush_ms = self.cfg.recorder.batch_flush_ms / 1000.0
        flush_rows = self.cfg.recorder.batch_flush_rows

        while not self._stop.is_set() or not self.q.empty():
            try:
                rec = self.q.get(timeout=flush_ms)
                batch_rows += self._handle(rec)
            except queue.Empty:
                pass

            now = time.monotonic()
            if batch_rows >= flush_rows or (now - last_flush) >= flush_ms:
                self.repo.flush()
                last_flush = now
                batch_rows = 0
                self._publish_counts()

        self.repo.flush()
        self._publish_counts()

    def _handle(self, rec: Rec) -> int:
        try:
            if rec.kind == TICK:
                return self.repo.insert_ticks([rec.payload])
            if rec.kind == CHAIN:
                return self.repo.insert_chain(rec.payload)
            if rec.kind == CANDLE:
                self.repo.insert_candle(rec.payload)
                return 1
            if rec.kind == REGIME:
                self.repo.insert_regime(rec.payload)
                return 1
            if rec.kind == JOURNAL:
                p = rec.payload
                self.repo.insert_journal(p["event"], p["kind"], p["approved"],
                                         p["pnl"], p["detail"], p["payload"],
                                         p["ts_ms"])
                return 1
        except Exception as exc:  # never let a bad row kill the recorder
            if self.notifier:
                self.notifier.warn(f"recorder write error: {exc}")
        return 0

    def _publish_counts(self) -> None:
        if self.state is None:
            return
        c = self.repo.counts()
        self.state.merge("recorder", {
            "ticks": c.get("ticks", 0),
            "chain_snaps": c.get("chain_snaps", 0),
            "dropped": self.dropped,
            "queue_depth": self.q.qsize(),
            "db_file": self.repo.db_path,
            "collecting": self._collecting.is_set(),
        })
