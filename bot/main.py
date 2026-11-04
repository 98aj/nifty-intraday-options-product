"""Engine entry point: wires every component and runs the session.

Threads (all daemon; trading is isolated on the worker thread):
  FeedThread            -> TickBus.publish
  RecorderFeeder        -> drains TickBus(all) into the Recorder queue
  Recorder              -> batched SQLite writes (independent)
  NIFTYWorker           -> candles/regime/strategy/risk/execution (trading)
  ChainPoller           -> option-chain snapshots -> recorder + worker
  SnapshotWriter        -> StateStore -> data/state/snapshot.json
  CommandAPI (uvicorn)  -> /state + /command
  Notifier              -> Telegram/console (+ inbound commands)

Control loop (main thread) drains commands and ends the session at market close.
"""
from __future__ import annotations

import datetime as dt
import json
import threading
import time
from pathlib import Path
from typing import Optional

import pytz

from bot.api.command_api import CommandApiServer
from bot.clock import Clock, SimClock, build_session_window, within_live_window
from bot.config import Config, load_config, project_root
from bot.core.commands import CommandQueue, CommandType
from bot.core.instrument_worker import InstrumentWorker
from bot.core.state_store import StateStore
from bot.core.tickbus import TickBus
from bot.data.instruments import ContractUniverse, sim_current_expiry
from bot.data.warmup import load_warmup_15m
from bot.execution.live import LiveExecutor
from bot.execution.paper import PaperExecutor
from bot.models import EngineStatus
from bot.notify.factory import build_notifier
from bot.recorder.recorder import Recorder
from bot.regime.iv_rank import IVRankProvider
from bot.risk.risk_manager import RiskManager
from bot.storage.sqlite_store import SQLiteRepository

IST = pytz.timezone("Asia/Kolkata")


class Engine:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.win = build_session_window(cfg.session)
        self._build_clock()
        self.state = StateStore()
        self.tickbus = TickBus()
        self.command_queue = CommandQueue()
        self.repo = SQLiteRepository(cfg)
        self.recorder = Recorder(cfg, self.repo, self.state,
                                 enabled=cfg.recorder.collect_on_start)
        self.notifier = build_notifier(cfg, self.command_queue,
                                       state_provider=self._status_text)
        self.recorder.notifier = self.notifier
        self.risk = RiskManager(cfg)
        self.iv_rank = IVRankProvider(cfg)
        self.contracts = ContractUniverse(cfg.instrument.lot_size,
                                          cfg.instrument.strike_step)
        self.executor = (PaperExecutor(cfg) if cfg.mode == "paper"
                         else LiveExecutor(cfg))
        self.feed = None
        self.chain = None
        self.worker: Optional[InstrumentWorker] = None
        self.api = CommandApiServer(cfg, self.state, self.command_queue)

        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self.session_date = self.clock.now().date()
        self.is_expiry = False

    # ---------------- setup ----------------
    def _build_clock(self) -> None:
        if self.cfg.simulate_feed:
            today = dt.datetime.now(IST).date()
            start = IST.localize(dt.datetime.combine(
                today, dt.datetime.strptime(
                    self.cfg.session.market_open, "%H:%M").time()))
            self.clock: Clock = SimClock(start, self.cfg.sim.speed_factor)
        else:
            self.clock = Clock()

    def _setup_data_layer(self) -> None:
        if self.cfg.simulate_feed:
            self._setup_sim()
        else:
            self._setup_live()

    def _setup_sim(self) -> None:
        from bot.data.sim_chain import SimChain
        from bot.data.sim_feed import SimFeed, build_sim_universe

        expiry = sim_current_expiry(self.session_date,
                                    self.cfg.instrument.sim_force_expiry_weekday)
        uni = build_sim_universe(self.cfg, expiry, self.cfg.sim.start_spot)
        self.contracts = uni
        self.is_expiry = (expiry == self.session_date.isoformat())

        feed = SimFeed(self.cfg, self.clock, uni)
        chain = SimChain(self.cfg, uni, feed.current_spot, feed.current_vix,
                         self.clock.now)
        feed.set_option_tick_source(chain)
        self.feed, self.chain = feed, chain

    def _setup_live(self) -> None:
        from bot.data.upstox_chain import UpstoxChain
        from bot.data.upstox_feed import UpstoxFeed

        token = self.cfg.secrets.upstox_access_token
        if not token:
            raise RuntimeError("UPSTOX_ACCESS_TOKEN missing; set simulate_feed: true "
                               "or provide a token.")
        chain = UpstoxChain(self.cfg, token, self.contracts)
        expiry = chain.discover_expiry_and_contracts()
        self.is_expiry = (expiry == self.session_date.isoformat())
        snap = chain.snapshot()
        spot = snap.spot if snap else 0.0

        window = self.contracts.window_keys(
            spot, self.cfg.recorder.tick_strikes_each_side) if spot else []
        initial = [self.cfg.instrument.underlying_key,
                   self.cfg.instrument.vix_key] + window
        feed = UpstoxFeed(self.cfg, token, initial)
        self.feed, self.chain = feed, chain

    def _live_window_ok(self) -> bool:
        """In live mode, refuse to contact Upstox outside the trading window.
        Guarantees no Upstox API calls after market hours / on holidays."""
        if self.cfg.simulate_feed:
            return True
        now = self.clock.now()
        closed = (self.risk.calendar.is_holiday(now.date())
                  or not within_live_window(self.win, now))
        if not closed:
            return True
        msg = ("Live mode: market closed (outside ~09:00-15:30 IST on a trading "
               "day) — NOT contacting Upstox. Use simulate_feed: true to run "
               "offline, or start during market hours.")
        print("[engine] " + msg, flush=True)
        self.notifier.start()
        self.notifier.warn(msg)
        self.state.update(status=EngineStatus.STOPPED.value,
                          halted_reason="market closed")
        time.sleep(0.5)
        self.notifier.stop()
        return False

    # ---------------- run ----------------
    def run(self) -> None:
        self.state.update(status=EngineStatus.STARTING.value, mode=self.cfg.mode,
                          simulate_feed=self.cfg.simulate_feed,
                          session_date=self.session_date.isoformat())
        if not self._live_window_ok():
            return
        self._setup_data_layer()
        self.state.update(is_expiry_day=self.is_expiry)

        day = self.session_date.isoformat()
        self.recorder.start(day)
        self.notifier.start()
        self.api.start()

        # IV rank warm-up + candle warm-up
        self.iv_rank.warm()
        session_open = IST.localize(dt.datetime.combine(
            self.session_date, self.win.open))
        warm = load_warmup_15m(self.cfg, session_open,
                               self.cfg.secrets.upstox_access_token,
                               self.cfg.instrument.underlying_key)

        # worker
        self.worker = InstrumentWorker(
            self.cfg, self.clock, self.state, self.recorder, self.notifier,
            self.risk, self.executor, self.chain, self.iv_rank, self.contracts)
        self.worker.seed_warmup(warm)

        # subscriptions
        rec_sub = self.tickbus.subscribe("recorder",
                                         maxsize=self.cfg.recorder.queue_maxsize,
                                         keys=None)
        worker_sub = self.tickbus.subscribe(
            "nifty", maxsize=20000,
            keys={self.cfg.instrument.underlying_key, self.cfg.instrument.vix_key})
        self.worker.attach_tick_sub(worker_sub)
        self.feed.set_on_tick(self.tickbus.publish)

        # bridge TickBus(all) -> recorder queue
        self._spawn(self._recorder_feeder, "RecorderFeeder", rec_sub)
        self.worker.start(self.is_expiry)
        self.feed.start()
        self._spawn(self._chain_poller, "ChainPoller")
        self._spawn(self._snapshot_writer, "SnapshotWriter")

        self.notifier.info(
            f"Engine up: mode={self.cfg.mode} sim={self.cfg.simulate_feed} "
            f"day={day} expiry={self.is_expiry} "
            f"strategy={'CONDOR' if self.is_expiry else 'regime-driven'}")
        self._control_loop()
        self._shutdown()

    # ---------------- threads ----------------
    def _spawn(self, target, name, *args) -> None:
        t = threading.Thread(target=target, name=name, args=args, daemon=True)
        t.start()
        self._threads.append(t)

    def _recorder_feeder(self, sub) -> None:
        import queue as _q
        while not self._stop.is_set():
            try:
                tick = sub.q.get(timeout=0.2)
            except _q.Empty:
                continue
            self.recorder.record_tick(tick)

    def _chain_poller(self) -> None:
        interval = self.cfg.recorder.chain_snapshot_interval_sec
        while not self._stop.is_set():
            if self._session_over():
                break
            try:
                snap = self.chain.snapshot()
            except Exception as exc:
                self.notifier.warn(f"chain poll error: {exc}")
                snap = None
            if snap is not None and snap.quotes:
                if self.cfg.recorder.enabled:
                    self.recorder.record_chain(snap)
                if self.worker:
                    self.worker.push_chain(snap)
                self.state.set_path("vix", snap.vix or self.state.snapshot()["vix"])
            time.sleep(interval)

    def _snapshot_writer(self) -> None:
        out = project_root() / self.cfg.storage.state_dir / "snapshot.json"
        tmp = out.with_suffix(".json.tmp")
        while not self._stop.is_set():
            try:
                snap = self.state.snapshot()
                tmp.write_text(json.dumps(snap, default=str))
                tmp.replace(out)
            except Exception:
                pass
            time.sleep(1.0)

    # ---------------- control ----------------
    def _control_loop(self) -> None:
        while not self._stop.is_set():
            if self._session_over():
                self.notifier.info("Market close reached -> squaring off + stopping.")
                break
            cmd = self.command_queue.get(timeout=0.3)
            if cmd is not None:
                self._handle_command(cmd)
            time.sleep(0.05)

    def _handle_command(self, cmd) -> None:
        t = cmd.type
        if t == CommandType.STATUS:
            self.notifier.info(self._status_text())
        elif t == CommandType.PAUSE:
            self.worker.pause()
            self.state.update(status=EngineStatus.PAUSED.value)
            self.notifier.info("paused (no new entries).")
        elif t == CommandType.RESUME:
            self.worker.resume()
            self.state.update(status=EngineStatus.RUNNING.value)
            self.notifier.info("resumed.")
        elif t == CommandType.FLATTEN:
            self.worker.request_flatten()
            self.notifier.alert("FLATTEN requested.")
        elif t == CommandType.KILL:
            self.worker.kill()
            self.notifier.alert("KILL switch: flatten all + halt.")
        elif t == CommandType.RECORD_ON:
            if not self.cfg.recorder.enabled:
                self.notifier.warn("recorder master switch is off (recorder.enabled). "
                                   "cannot start collection.")
            else:
                self.recorder.enable()
                self.notifier.info("data collection ON (ticks + chain recording).")
        elif t == CommandType.RECORD_OFF:
            self.recorder.disable()
            self.notifier.info("data collection OFF (journal/regime still logged).")

    def _session_over(self) -> bool:
        return self.clock.now().time() >= self.win.close

    def _status_text(self) -> str:
        s = self.state.snapshot()
        pos = s.get("position")
        pos_s = "flat"
        if pos and pos.get("open"):
            pos_s = f"{pos['kind']} pnl {pos.get('pnl', 0):.0f}"
        reg = s.get("regime") or {}
        return (f"status={s.get('status')} mode={s.get('mode')} "
                f"sim={s.get('simulate_feed')} | NIFTY {s['underlying'].get('ltp')} "
                f"VIX {s.get('vix')} | regime={reg.get('regime')} "
                f"conf={reg.get('confidence')} | {pos_s} | "
                f"pnl_day {s.get('pnl_day')} trades {s.get('trades_today')} | "
                f"recording {'ON' if s['recorder'].get('collecting') else 'OFF'} "
                f"ticks {s['recorder'].get('ticks')} "
                f"chain {s['recorder'].get('chain_snaps')} "
                f"dropped {s['recorder'].get('dropped')}")

    # ---------------- shutdown ----------------
    def _shutdown(self) -> None:
        self._stop.set()
        try:
            if self.worker:
                self.worker.stop()
        except Exception:
            pass
        try:
            self.feed.stop()
        except Exception:
            pass
        self.state.update(status=EngineStatus.STOPPED.value)
        time.sleep(0.5)
        self.recorder.stop()
        self.api.stop()
        self.notifier.info(self._status_text())
        self.notifier.info("Engine stopped. Data recorded to "
                           f"{self.repo.db_path}")
        self.notifier.stop()
        print("[engine] stopped.", flush=True)


def main() -> None:
    cfg = load_config()
    engine = Engine(cfg)
    try:
        engine.run()
    except KeyboardInterrupt:
        print("\n[engine] interrupt -> shutting down")
        engine._shutdown()


if __name__ == "__main__":
    main()
