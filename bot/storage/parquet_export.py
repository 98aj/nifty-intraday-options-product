"""Daily SQLite -> partitioned Parquet export (the v2 backtester reads Parquet).

Converts each table of a day's DB into Parquet under data/parquet/<table>/date=<day>/.
Uses polars (fast, columnar). Safe to re-run; overwrites that day's partition.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import polars as pl

from bot.config import Config, project_root

TABLES = ["ticks", "chain_snapshots", "candles", "regime_log", "journal"]


def export_day(cfg: Config, day: str) -> dict[str, int]:
    root = project_root()
    db_path = root / cfg.storage.db_dir / f"{day}.db"
    if not db_path.exists():
        raise FileNotFoundError(f"No DB for {day}: {db_path}")
    out_root = root / cfg.storage.parquet_dir
    out_root.mkdir(parents=True, exist_ok=True)

    written: dict[str, int] = {}
    uri = f"sqlite://{db_path.as_posix()}"
    conn = sqlite3.connect(str(db_path))
    try:
        for table in TABLES:
            try:
                df = pl.read_database(f"SELECT * FROM {table}", connection=conn)
            except Exception:
                written[table] = 0
                continue
            part_dir = out_root / table / f"date={day}"
            part_dir.mkdir(parents=True, exist_ok=True)
            out_file = part_dir / f"{table}.parquet"
            df.write_parquet(out_file)
            written[table] = df.height
    finally:
        conn.close()
    return written


def export_latest(cfg: Config) -> dict[str, int]:
    root = project_root()
    db_dir = root / cfg.storage.db_dir
    dbs = sorted(db_dir.glob("*.db"))
    if not dbs:
        raise FileNotFoundError("No daily DB files to export")
    day = dbs[-1].stem
    return export_day(cfg, day)
