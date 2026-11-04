"""Command-line helpers: Parquet export, Excel/CSV export, quick status.

Usage:
  python -m bot.cli export-parquet [YYYY-MM-DD|latest]
  python -m bot.cli export-excel   [YYYY-MM-DD|latest]
  python -m bot.cli export-csv     [YYYY-MM-DD|latest]
  python -m bot.cli status
  python -m bot.cli days
"""
from __future__ import annotations

import sys

import httpx

from bot.config import load_config, project_root
from bot.storage import excel_export, parquet_export


def _latest_day(cfg) -> str:
    db_dir = project_root() / cfg.storage.db_dir
    dbs = sorted(db_dir.glob("*.db"))
    if not dbs:
        raise SystemExit("No daily DB files found in " + str(db_dir))
    return dbs[-1].stem


def _resolve_day(cfg, arg: str | None) -> str:
    if arg in (None, "latest"):
        return _latest_day(cfg)
    return arg


def cmd_export_parquet(cfg, arg):
    day = _resolve_day(cfg, arg)
    written = parquet_export.export_day(cfg, day)
    print(f"Parquet export for {day}:")
    for table, n in written.items():
        print(f"  {table:16s} {n:>10,} rows")
    print("-> " + str(project_root() / cfg.storage.parquet_dir))


def cmd_export_excel(cfg, arg):
    day = _resolve_day(cfg, arg)
    path = excel_export.export_excel(cfg, day)
    print(f"Excel export for {day} -> {path}")


def cmd_export_csv(cfg, arg):
    day = _resolve_day(cfg, arg)
    paths = excel_export.export_csv(cfg, day)
    print(f"CSV export for {day}:")
    for p in paths:
        print("  " + p)


def cmd_status(cfg, _arg):
    url = cfg.ui.engine_state_url
    try:
        r = httpx.get(url, timeout=5)
        s = r.json()
    except Exception as exc:
        raise SystemExit(f"Engine not reachable at {url}: {exc}")
    print(f"status={s.get('status')} mode={s.get('mode')} "
          f"sim={s.get('simulate_feed')}")
    print(f"NIFTY={s['underlying'].get('ltp')} VIX={s.get('vix')} "
          f"regime={(s.get('regime') or {}).get('regime')}")
    print(f"pnl_day={s.get('pnl_day')} trades={s.get('trades_today')}")
    print(f"recorder: {s.get('recorder')}")


def cmd_days(cfg, _arg):
    db_dir = project_root() / cfg.storage.db_dir
    for p in sorted(db_dir.glob("*.db")):
        print(p.stem)


def main() -> None:
    cfg = load_config()
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    cmd = args[0]
    arg = args[1] if len(args) > 1 else None
    dispatch = {
        "export-parquet": cmd_export_parquet,
        "export-excel": cmd_export_excel,
        "export-csv": cmd_export_csv,
        "status": cmd_status,
        "days": cmd_days,
    }
    fn = dispatch.get(cmd)
    if fn is None:
        print(__doc__)
        raise SystemExit(f"unknown command: {cmd}")
    fn(cfg, arg)


if __name__ == "__main__":
    main()
