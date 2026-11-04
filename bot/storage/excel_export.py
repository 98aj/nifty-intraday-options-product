"""On-demand Excel/CSV export (pandas) to review trades + recorded data.

Excel: one workbook with a sheet per table (trades/journal first).
CSV: one file per table in a dated folder.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from bot.config import Config, project_root

TABLES = ["journal", "regime_log", "candles", "chain_snapshots", "ticks"]


def _read(conn, table: str) -> pd.DataFrame:
    try:
        return pd.read_sql_query(f"SELECT * FROM {table}", conn)
    except Exception:
        return pd.DataFrame()


def export_excel(cfg: Config, day: str, out_path: str | None = None) -> str:
    root = project_root()
    db_path = root / cfg.storage.db_dir / f"{day}.db"
    if not db_path.exists():
        raise FileNotFoundError(f"No DB for {day}: {db_path}")
    out = Path(out_path) if out_path else (
        root / cfg.storage.parquet_dir.replace("parquet", "exports")
        / f"review_{day}.xlsx")
    out.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    try:
        with pd.ExcelWriter(out, engine="openpyxl") as xl:
            for table in TABLES:
                df = _read(conn, table)
                # cap very large sheets (Excel row limit ~1,048,576)
                if len(df) > 1_000_000:
                    df = df.tail(1_000_000)
                sheet = table[:31]
                (df if not df.empty else pd.DataFrame({"_": ["(empty)"]})
                 ).to_excel(xl, sheet_name=sheet, index=False)
    finally:
        conn.close()
    return str(out)


def export_csv(cfg: Config, day: str) -> list[str]:
    root = project_root()
    db_path = root / cfg.storage.db_dir / f"{day}.db"
    if not db_path.exists():
        raise FileNotFoundError(f"No DB for {day}: {db_path}")
    out_dir = root / "data" / "exports" / day
    out_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    written: list[str] = []
    try:
        for table in TABLES:
            df = _read(conn, table)
            fp = out_dir / f"{table}.csv"
            df.to_csv(fp, index=False)
            written.append(str(fp))
    finally:
        conn.close()
    return written
