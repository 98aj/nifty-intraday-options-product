import time

from bot.models import Tick
from bot.recorder.recorder import Recorder
from bot.storage.sqlite_store import SQLiteRepository


def _tick(i):
    return Tick(instrument_key="NSE_INDEX|Nifty 50", symbol="NIFTY",
                ltp=24000 + i, exch_ts_ms=1000 + i, recv_ts_ms=1000 + i,
                volume=0)


def test_recorder_batches_to_sqlite(cfg, tmp_path):
    cfg.storage.db_dir = str(tmp_path)
    cfg.recorder.batch_flush_rows = 50
    cfg.recorder.batch_flush_ms = 50
    repo = SQLiteRepository(cfg)
    rec = Recorder(cfg, repo)
    rec.start("2026-11-10")
    for i in range(200):
        rec.record_tick(_tick(i))
    # allow the writer thread to drain + flush
    deadline = time.time() + 5
    while time.time() < deadline and repo.counts()["ticks"] < 200:
        time.sleep(0.05)
    rec.stop()
    assert repo.counts()["ticks"] == 200


def test_toggle_gates_ticks_but_not_journal(cfg, tmp_path):
    cfg.storage.db_dir = str(tmp_path)
    repo = SQLiteRepository(cfg)
    rec = Recorder(cfg, repo, enabled=False)   # start with collection OFF
    rec.start("2026-11-10")
    assert rec.is_collecting() is False

    # ticks dropped while OFF
    for i in range(20):
        rec.record_tick(_tick(i))
    # journal still records while collection is OFF (audit trail)
    rec.record_journal("INFO", "", None, None, "while off", {}, ts_ms=1)

    # turn ON -> ticks now persist
    rec.enable()
    assert rec.is_collecting() is True
    for i in range(30):
        rec.record_tick(_tick(100 + i))

    deadline = time.time() + 5
    while time.time() < deadline and repo.counts()["ticks"] < 30:
        time.sleep(0.05)
    rec.stop()

    assert repo.counts()["ticks"] == 30          # only the ones recorded while ON
    assert repo.counts()["journal"] == 1         # journal logged even while OFF


def test_queue_overflow_counts_drops(cfg, tmp_path):
    cfg.storage.db_dir = str(tmp_path)
    cfg.recorder.queue_maxsize = 10
    repo = SQLiteRepository(cfg)
    rec = Recorder(cfg, repo)
    # do NOT start the writer -> queue fills and overflows
    for i in range(50):
        rec.record_tick(_tick(i))
    assert rec.dropped > 0
