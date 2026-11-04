"""End-to-end sim smoke test: the whole engine runs with NO token, records ticks +
chain snapshots, and keeps recording regardless of trading. Proves the non-blocking
pipeline wires together."""
import sqlite3
import threading
import time

from bot.config import load_config
from bot.main import Engine


def test_engine_runs_and_records(tmp_path):
    cfg = load_config()
    cfg.simulate_feed = True
    cfg.mode = "paper"
    cfg.sim.speed_factor = 1500        # compress the session
    cfg.sim.tick_interval_ms = 20
    cfg.recorder.chain_snapshot_interval_sec = 1
    cfg.recorder.strikes_each_side = 5
    cfg.recorder.tick_strikes_each_side = 2
    cfg.recorder.collect_on_start = True   # default is OFF; turn on for the smoke test
    cfg.api.port = 8199                # avoid clashing with a running engine
    for name in ("db", "parquet", "state", "logs"):
        d = tmp_path / name
        d.mkdir()
    cfg.storage.db_dir = str(tmp_path / "db")
    cfg.storage.parquet_dir = str(tmp_path / "parquet")
    cfg.storage.state_dir = str(tmp_path / "state")
    cfg.storage.log_dir = str(tmp_path / "logs")

    engine = Engine(cfg)
    t = threading.Thread(target=engine.run, daemon=True)
    t.start()

    # let it record for a few seconds, then stop cleanly
    time.sleep(6.0)
    engine._stop.set()
    t.join(timeout=20)

    db_path = engine.repo.db_path
    assert db_path, "no db file created"
    conn = sqlite3.connect(db_path)
    try:
        ticks = conn.execute("SELECT COUNT(*) FROM ticks").fetchone()[0]
        chain = conn.execute("SELECT COUNT(*) FROM chain_snapshots").fetchone()[0]
    finally:
        conn.close()

    assert ticks > 0, "recorder captured no ticks"
    assert chain > 0, "recorder captured no chain snapshots"
