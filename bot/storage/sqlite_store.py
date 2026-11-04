"""SQLite repository: daily DB files, WAL mode, batched inserts.

Owned by the recorder's single writer thread. Ticks/chain rows are buffered and
flushed in one transaction per batch (never one txn per row) for high write
throughput, so recording never stalls trading.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Sequence

from bot.config import project_root
from bot.models import Candle, ChainSnapshot, RegimeDecision, Tick


SCHEMA_PATH = Path(__file__).with_name("schema.sql")


class SQLiteRepository:
    def __init__(self, cfg) -> None:
        self.cfg = cfg
        self.db_dir = project_root() / cfg.storage.db_dir
        self.db_dir.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._path: Path | None = None
        self._tick_buf: list[tuple] = []
        self._chain_buf: list[tuple] = []
        self._counts = {"ticks": 0, "chain_snaps": 0, "candles": 0,
                        "regime": 0, "journal": 0}

    @property
    def db_path(self) -> str:
        return str(self._path) if self._path else ""

    def open_day(self, day: str) -> None:
        self._path = self.db_dir / f"{day}.db"
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        if self.cfg.storage.wal:
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._conn.execute("PRAGMA temp_store=MEMORY;")
        self._conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        self._conn.commit()

    # ---------------- ticks ----------------
    def insert_ticks(self, ticks: Sequence[Tick]) -> int:
        for t in ticks:
            depth = None
            if t.bids or t.asks:
                depth = json.dumps({
                    "bids": [[d.price, d.qty] for d in t.bids],
                    "asks": [[d.price, d.qty] for d in t.asks],
                })
            bq = t.bids[0].qty if t.bids else 0
            aq = t.asks[0].qty if t.asks else 0
            self._tick_buf.append((
                t.exch_ts_ms, t.recv_ts_ms, ist_str_ms(t.recv_ts_ms),
                t.instrument_key, t.symbol, t.ltp, t.ltq, t.atp, t.volume,
                t.total_buy_qty, t.total_sell_qty, t.oi, t.oi_change,
                t.best_bid, t.best_ask, bq, aq, depth,
            ))
        return len(ticks)

    # ---------------- chain ----------------
    def insert_chain(self, snap: ChainSnapshot) -> int:
        ist = ist_str_ms(snap.ts_ms)
        for q in snap.quotes:
            self._chain_buf.append((
                snap.ts_ms, ist, snap.spot, snap.vix, snap.expiry,
                q.strike, q.opt_type.value, q.instrument_key, q.ltp, q.bid, q.ask,
                q.bid_qty, q.ask_qty, q.volume, q.oi, q.oi_change,
                q.iv, q.delta, q.gamma, q.theta, q.vega, q.rho,
            ))
        self._counts["chain_snaps"] += 1
        return len(snap.quotes)

    # ---------------- candles / regime / journal (immediate, small) --------
    def insert_candle(self, c: Candle) -> None:
        self._ensure()
        self._conn.execute(
            "INSERT INTO candles(instrument,tf_min,start_ms,end_ms,ist,open,high,"
            "low,close,volume) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (c.instrument_key, c.tf_min, c.start_ms, c.end_ms,
             ist_str_ms(c.start_ms), c.open, c.high, c.low, c.close, c.volume))
        self._conn.commit()
        self._counts["candles"] += 1

    def insert_regime(self, d: RegimeDecision) -> None:
        self._ensure()
        self._conn.execute(
            "INSERT INTO regime_log(ts_ms,ist,regime,raw_regime,confidence,adx,"
            "adx_slope,chop,vix,bias,reason) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (d.ts_ms, ist_str_ms(d.ts_ms), d.regime.value, d.raw_regime.value,
             d.confidence, d.adx, d.adx_slope, d.chop, d.vix, d.bias, d.reason))
        self._conn.commit()
        self._counts["regime"] += 1

    def insert_journal(self, event: str, kind: str, approved, pnl,
                       detail: str, payload: dict, ts_ms: int) -> None:
        self._ensure()
        self._conn.execute(
            "INSERT INTO journal(ts_ms,ist,event,kind,approved,pnl,detail,payload)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (ts_ms, ist_str_ms(ts_ms), event, kind,
             None if approved is None else int(approved),
             pnl, detail, json.dumps(payload, default=str)))
        self._conn.commit()
        self._counts["journal"] += 1

    # ---------------- flush buffered high-rate rows ----------------
    def flush(self) -> None:
        if self._conn is None:
            return
        if self._tick_buf:
            self._conn.executemany(
                "INSERT INTO ticks(exch_ts_ms,recv_ts_ms,ist,instrument,symbol,"
                "ltp,ltq,atp,volume,total_buy_qty,total_sell_qty,oi,oi_change,"
                "best_bid,best_ask,bid_qty,ask_qty,depth_json) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", self._tick_buf)
            self._counts["ticks"] += len(self._tick_buf)
            self._tick_buf.clear()
        if self._chain_buf:
            self._conn.executemany(
                "INSERT INTO chain_snapshots(ts_ms,ist,spot,vix,expiry,strike,"
                "opt_type,instrument,ltp,bid,ask,bid_qty,ask_qty,volume,oi,"
                "oi_change,iv,delta,gamma,theta,vega,rho) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", self._chain_buf)
            self._chain_buf.clear()
        self._conn.commit()

    def counts(self) -> dict:
        return dict(self._counts)

    def close(self) -> None:
        if self._conn is not None:
            try:
                self.flush()
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            except Exception:
                pass
            self._conn.close()
            self._conn = None

    def _ensure(self) -> None:
        if self._conn is None:
            raise RuntimeError("Repository day not opened; call open_day() first")


def ist_str_ms(ms: int) -> str:
    import datetime as _dt
    import pytz
    dt = _dt.datetime.fromtimestamp(ms / 1000.0, tz=pytz.UTC).astimezone(
        pytz.timezone("Asia/Kolkata"))
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
