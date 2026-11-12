"""Per-instrument trading worker thread (NIFTY in Phase 1).

ALL trading decisions for one instrument happen on THIS single thread, so no other
instrument (BANKNIFTY later) and no reader can delay its trades. It consumes ticks
from its TickBus queue and chain snapshots from the poller, builds 5m/15m candles,
runs the regime engine on 15m closes, routes the day-switch strategy, enforces exits
and session square-off, and journals everything via the recorder.

Trading is never blocked by recording/UI: this thread only ever enqueues records
(non-blocking) and reads immutable chain snapshots.
"""
from __future__ import annotations

import datetime as dt
import queue
import threading
from typing import Optional

import pytz

from bot.clock import build_session_window, ist_str_ms, squareoff_time
from bot.data.candles import CandleBuilder
from bot.execution.base import ExecutorBase
from bot.execution.pnl import gross_pnl, unrealized_pnl
from bot.models import (Candle, ChainSnapshot, EngineStatus, OrderIntent,
                        Position, Regime, StrategyKind, Tick, to_jsonable)
from bot.recorder.recorder import Recorder
from bot.regime.regime_engine import RegimeEngine
from bot.risk.risk_manager import RiskManager
from bot.strategy.base import StrategyContext
from bot.strategy.day_switch import DaySwitch

IST = pytz.timezone("Asia/Kolkata")


class InstrumentWorker:
    def __init__(self, cfg, clock, state_store, recorder: Recorder, notifier,
                 risk: RiskManager, executor: ExecutorBase,
                 chain_provider, iv_rank_provider, contracts) -> None:
        self.cfg = cfg
        self.clock = clock
        self.state = state_store
        self.recorder = recorder
        self.notify = notifier
        self.risk = risk
        self.executor = executor
        self.chain_provider = chain_provider
        self.iv_rank = iv_rank_provider
        self.contracts = contracts
        self.win = build_session_window(cfg.session)

        self.underlying_key = cfg.instrument.underlying_key
        self.vix_key = cfg.instrument.vix_key
        self.day_switch = DaySwitch(cfg)
        self.regime_engine = RegimeEngine(cfg)

        self.c5 = CandleBuilder(self.underlying_key, cfg.strategy.timeframe_entry_min,
                                on_close=self._on_5m_close)
        self.c15 = CandleBuilder(self.underlying_key, cfg.strategy.timeframe_bias_min,
                                 on_close=self._on_15m_close)

        self._tick_sub = None
        self._chain_q: "queue.Queue[ChainSnapshot]" = queue.Queue(maxsize=100)
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._flatten = threading.Event()
        self._killed = threading.Event()

        self.spot = 0.0
        self.vix = 0.0
        self.position: Optional[Position] = None
        self.last_regime = None
        self.is_expiry = False

    # ---- wiring ----
    def attach_tick_sub(self, sub) -> None:
        self._tick_sub = sub

    def set_executor(self, executor) -> None:
        """Hot-swap the executor (paper <-> live) from the control loop."""
        self.executor = executor

    def push_chain(self, snap: ChainSnapshot) -> None:
        try:
            self._chain_q.put_nowait(snap)
        except queue.Full:
            pass

    def seed_warmup(self, bars_15m: list[Candle]) -> None:
        for b in bars_15m:
            self.c15.add_candle(Candle(self.underlying_key, 15, b.start_ms,
                                       b.end_ms, b.open, b.high, b.low, b.close,
                                       b.volume, True))
        # Publish an initial regime straight away so the dashboard isn't blank
        # after a restart (otherwise it stays UNKNOWN until the first live 15m
        # close). Computed on the warm-up bars as a prior; refined on each live
        # 15m close. VIX may be 0 here (no tick yet) -> only affects the spike
        # check, which self-corrects at the first live close.
        self.state.set_path("candles_15m", self._recent(self.c15.closed))
        decision = self.regime_engine.update(self.c15.closed, self.vix)
        if decision is not None:
            self.last_regime = decision
            self.state.set_path("regime", to_jsonable(decision))

    # ---- control ----
    def pause(self) -> None:
        self._paused.set()
        self._journal("INFO", "", None, None, "paused")

    def resume(self) -> None:
        self._paused.clear()
        self._journal("INFO", "", None, None, "resumed")

    def request_flatten(self) -> None:
        self._flatten.set()

    def kill(self) -> None:
        self._killed.set()
        self._flatten.set()

    # ---- lifecycle ----
    def start(self, is_expiry: bool) -> None:
        self.is_expiry = is_expiry
        self._thread = threading.Thread(target=self._run, name="NIFTYWorker",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5.0)

    def _run(self) -> None:
        self.state.update(status=EngineStatus.RUNNING.value)
        while not self._stop.is_set():
            # 1) drain any chain snapshots (trading decisions happen here)
            self._drain_chain()
            # 2) process a tick (short timeout keeps loop responsive)
            if self._tick_sub is not None:
                try:
                    tick = self._tick_sub.q.get(timeout=0.1)
                    self._on_tick(tick)
                except queue.Empty:
                    pass
            else:
                self._stop.wait(0.1)
        # final close on stop
        self._force_squareoff("engine stop")

    # ---- tick handling ----
    def _on_tick(self, tick: Tick) -> None:
        if tick.instrument_key == self.underlying_key:
            self.spot = tick.ltp
            self.c5.add_tick(tick.recv_ts_ms, tick.ltp, tick.volume)
            self.c15.add_tick(tick.recv_ts_ms, tick.ltp, tick.volume)
            self.state.merge("underlying", {"symbol": "NIFTY", "ltp": tick.ltp,
                                            "ts_ms": tick.recv_ts_ms})
        elif tick.instrument_key == self.vix_key:
            self.vix = tick.ltp
            self.state.set_path("vix", tick.ltp)

    def _drain_chain(self) -> None:
        latest: Optional[ChainSnapshot] = None
        while True:
            try:
                latest = self._chain_q.get_nowait()
            except queue.Empty:
                break
        if latest is not None:
            self._on_chain(latest)

    # ---- candle close callbacks ----
    def _on_5m_close(self, candle: Candle) -> None:
        self.recorder.record_candle(candle)
        self.state.set_path("candles_5m", self._recent(self.c5.closed))
        self._try_entry(trigger="5m_close")

    def _on_15m_close(self, candle: Candle) -> None:
        self.recorder.record_candle(candle)
        self.state.set_path("candles_15m", self._recent(self.c15.closed))
        decision = self.regime_engine.update(self.c15.closed, self.vix)
        if decision is not None:
            self.last_regime = decision
            self.recorder.record_regime(decision)
            self.state.set_path("regime", to_jsonable(decision))
            self._journal("REGIME", "", None, None, decision.reason,
                          to_jsonable(decision), ts_ms=decision.ts_ms)

    # ---- chain-driven: exits, halts, square-off ----
    def _on_chain(self, snap: ChainSnapshot) -> None:
        now = self.clock.now()
        # mark open position
        if self.position and self.position.open:
            self.position.pnl = unrealized_pnl(self.position, snap)
            self.position.current_net = gross_pnl(self.position, snap)
            self.state.set_path("position", to_jsonable(self.position))
            self.state.set_path("pnl_day", round(
                self.risk.state.realized_pnl + self.position.pnl, 2))
        else:
            self.state.set_path("pnl_day", round(self.risk.state.realized_pnl, 2))

        # kill / flatten requests
        if self._flatten.is_set():
            self._force_squareoff("flatten/kill command")
            self._flatten.clear()
            if self._killed.is_set():
                self.risk.halt("kill switch")
                self.state.update(status=EngineStatus.HALTED.value,
                                  halted_reason="kill switch")
            return

        # daily halt check (continuous)
        unreal = self.position.pnl if (self.position and self.position.open) else 0.0
        halt_reason = self.risk.check_daily_halt(unreal)
        if halt_reason and not self.risk.state.halted:
            self._force_squareoff(halt_reason)
            self.risk.halt(halt_reason)
            self.state.update(status=EngineStatus.HALTED.value,
                              halted_reason=halt_reason)
            self.notify.alert(halt_reason)
            return

        # time-based square-off
        so = squareoff_time(self.win, self.is_expiry)
        if now.time() >= so and self.position and self.position.open:
            self._force_squareoff(f"square-off {so.strftime('%H:%M')}")
            return

        # manage exits on the open position
        if self.position and self.position.open:
            self._check_exits(snap, now)

    def _check_exits(self, snap: ChainSnapshot, now: dt.datetime) -> None:
        p = self.position
        if p.pnl >= p.take_profit_level > 0:
            self._close(snap, f"take-profit {p.take_profit_level:.0f}")
        elif p.pnl <= p.stop_loss_level < 0:
            self._close(snap, f"stop-loss {p.stop_loss_level:.0f}")

    # ---- entries ----
    def _set_decision(self, *, kind: str = "", kind_reason: str = "",
                      approved=None, risk_note=None, max_risk=None,
                      max_reward=None, est_costs=None, past_cutoff: bool = False,
                      action: str = "", trigger: str = "", iv_rank=None) -> None:
        """Publish the live decision pipeline (regime -> strategy -> risk ->
        action) so the dashboard can show what the bot is thinking."""
        reg = self.last_regime
        self.state.set_path("decision", {
            "ts_ms": int(self.clock.now().timestamp() * 1000),
            "trigger": trigger,
            "regime": (reg.regime.value if reg else "UNKNOWN"),
            "confidence": (reg.confidence if reg else 0.0),
            "iv_rank": iv_rank,
            "kind": kind,
            "kind_reason": kind_reason,
            "approved": approved,
            "risk_note": risk_note,
            "max_risk": max_risk,
            "max_reward": max_reward,
            "est_costs": est_costs,
            "past_cutoff": past_cutoff,
            "is_expiry": self.is_expiry,
            "action": action,
        })

    def _try_entry(self, trigger: str) -> None:
        if self._paused.is_set():
            self._set_decision(action="Paused — no new entries", trigger=trigger)
            return
        if self.risk.state.halted:
            self._set_decision(action="Trading halted — see banner",
                               trigger=trigger)
            return
        if self.position and self.position.open:
            self._set_decision(kind=self.position.kind.value,
                               action="In position — managing exit",
                               trigger=trigger)
            return
        snap = self.chain_provider.snapshot() if self.chain_provider else None
        if snap is None or not snap.quotes:
            self._set_decision(action="Waiting for option-chain data",
                               trigger=trigger)
            return
        now = self.clock.now()
        past_cutoff = now.time() >= self.win.no_new_entry_after
        iv_rank = self.iv_rank.current()

        ctx = StrategyContext(
            now_ms=int(now.timestamp() * 1000), chain=snap,
            candles_5m=self.c5.closed, candles_15m=self.c15.closed,
            regime=self.last_regime, is_expiry=self.is_expiry, vix=self.vix,
            iv_rank=iv_rank, lot_size=self.contracts.lot_size,
            num_lots=max(1, int(self.cfg.capital.lots)))

        kind, reason, intent = self.day_switch.build_entry(ctx)
        self.state.set_path("strategy_today", kind.value)
        if intent is None:
            self._journal("SIGNAL", kind.value, None, None,
                          f"flat: {reason}", {"trigger": trigger})
            action = ("Standing aside — no setup" if kind == StrategyKind.FLAT
                      else "No valid entry built this cycle")
            self._set_decision(kind=kind.value, kind_reason=reason,
                               past_cutoff=past_cutoff, action=action,
                               trigger=trigger, iv_rank=iv_rank)
            return

        self._journal("SIGNAL", kind.value, None, None,
                      intent.reason, to_jsonable(intent))
        decision = self.risk.evaluate(intent, now, self.vix, self.is_expiry,
                                      past_cutoff)
        self._journal("RISK", kind.value, decision.approved, None,
                      decision.reason, {"max_risk": decision.max_risk,
                                        "max_reward": decision.max_reward,
                                        "est_costs": decision.est_costs})
        self.state.set_path("last_signal",
                            {"kind": kind.value, "reason": intent.reason,
                             "approved": decision.approved,
                             "risk_note": decision.reason})
        self._set_decision(
            kind=kind.value, kind_reason=reason, approved=decision.approved,
            risk_note=decision.reason, max_risk=decision.max_risk,
            max_reward=decision.max_reward, est_costs=decision.est_costs,
            past_cutoff=past_cutoff, trigger=trigger, iv_rank=iv_rank,
            action=("Entry approved — opening position" if decision.approved
                    else "Blocked by risk gate"))
        if not decision.approved:
            return
        self._open(intent, snap, now)

    def _open(self, intent: OrderIntent, snap: ChainSnapshot,
              now: dt.datetime) -> None:
        ts = int(now.timestamp() * 1000)
        try:
            pos = self.executor.open_position(intent, snap, ts)
        except NotImplementedError as exc:
            # e.g. LiveExecutor in Phase 1 — halt safely, never crash the thread.
            reason = f"execution unavailable: {exc}"
            self.risk.halt(reason)
            self.state.update(status=EngineStatus.HALTED.value, halted_reason=reason)
            self._journal("ORDER", intent.kind.value, False, None, reason, {})
            self.notify.alert(reason)
            return
        self.position = pos
        self.risk.on_open()
        self.state.set_path("position", to_jsonable(pos))
        self.state.update(trades_today=self.risk.state.trades_today)
        self._journal("ORDER", pos.kind.value, True, None,
                      f"OPEN {pos.kind.value} net {pos.entry_net:.1f} "
                      f"risk {pos.max_risk:.0f}", to_jsonable(pos), ts_ms=ts)
        self.notify.trade(f"OPEN {pos.kind.value}: entry net {pos.entry_net:.1f}, "
                          f"risk {pos.max_risk:.0f}, reward {pos.max_reward:.0f}")

    def _close(self, snap: ChainSnapshot, reason: str) -> None:
        if not (self.position and self.position.open):
            return
        ts = int(self.clock.now().timestamp() * 1000)
        realized = self.executor.close_position(self.position, snap, ts, reason)
        self.risk.on_close(realized)
        self.state.set_path("position", to_jsonable(self.position))
        self.state.set_path("realized_pnl_day", round(self.risk.state.realized_pnl, 2))
        self.state.set_path("pnl_day", round(self.risk.state.realized_pnl, 2))
        self._journal("FILL", self.position.kind.value, None, round(realized, 2),
                      f"CLOSE ({reason}) pnl {realized:.1f}",
                      to_jsonable(self.position), ts_ms=ts)
        self.notify.trade(f"CLOSE {self.position.kind.value} ({reason}): "
                          f"pnl {realized:.1f}")
        p = self.position
        self.state.push_trade({
            "entry_ist": ist_str_ms(p.entry_ts_ms),
            "exit_ist": ist_str_ms(ts),
            "kind": p.kind.value,
            "legs": len(p.legs),
            "entry_net": round(p.entry_net, 1),
            "pnl": round(realized, 1),
            "risk": round(p.max_risk, 0),
            "reason": reason,
        })
        self.state.set_path("trades_today", self.risk.state.trades_today)
        self.position = None

    def _force_squareoff(self, reason: str) -> None:
        if self.position and self.position.open:
            snap = self.chain_provider.snapshot() if self.chain_provider else None
            if snap is not None:
                self._close(snap, reason)
            self.state.update(status=EngineStatus.SQUARED_OFF.value)

    # ---- helpers ----
    def _recent(self, candles: list[Candle], n: int = 30) -> list[dict]:
        return [to_jsonable(c) for c in candles[-n:]]

    def _journal(self, event: str, kind: str, approved, pnl, detail: str,
                 payload: dict, ts_ms: Optional[int] = None) -> None:
        ts = ts_ms if ts_ms is not None else int(self.clock.now().timestamp() * 1000)
        self.recorder.record_journal(event, kind, approved, pnl, detail, payload, ts)
        self.state.push_journal(f"{event} {kind} {detail}")
