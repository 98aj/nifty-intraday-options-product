"""Typed configuration loaded from config/config.yaml + .env secrets.

All tunables live in YAML; secrets live in .env. Nothing here is hard-coded
business logic — this is the single source of truth for thresholds.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field


# --------------------------------------------------------------------------
# Nested config models (mirror config.yaml)
# --------------------------------------------------------------------------
class SessionCfg(BaseModel):
    market_open: str = "09:15"
    market_close: str = "15:30"
    no_new_entry_after: str = "14:30"
    hard_squareoff: str = "15:00"
    expiry_squareoff: str = "14:30"


class InstrumentCfg(BaseModel):
    underlying_symbol: str = "NIFTY"
    underlying_key: str = "NSE_INDEX|Nifty 50"
    vix_key: str = "NSE_INDEX|India VIX"
    exchange: str = "NSE_FO"
    lot_size: int = 75
    strike_step: int = 50
    sim_force_expiry_weekday: int = 1


class CapitalCfg(BaseModel):
    total: float = 500000
    max_risk_per_trade_pct: float = 1.0
    daily_max_loss_pct: float = 3.0
    daily_profit_target_pct: float = 0.0
    max_open_positions: int = 1
    max_trades_per_day: int = 4


class RegimeCfg(BaseModel):
    adx_period: int = 14
    adx_trend_min: float = 22
    adx_slope_lookback: int = 3
    chop_period: int = 14
    chop_trend_max: float = 38.2
    chop_range_min: float = 61.8
    vix_spike_pct: float = 12.0
    confirmations_required: int = 2
    min_dwell_bars: int = 2
    confidence_min: float = 0.55


class IVRankCfg(BaseModel):
    source: str = "vix_percentile"
    lookback_days: int = 250
    high_threshold: float = 50.0


class IronCondorCfg(BaseModel):
    short_delta_target: float = 0.18
    wing_width_points: int = 100
    take_profit_pct: float = 0.50
    stop_loss_mult: float = 1.75
    min_credit_points: float = 20
    max_vix_to_enter: float = 16.0
    fallback_short_offset_steps: int = 5   # used when live greeks/delta missing


class DebitSpreadCfg(BaseModel):
    long_offset_steps: int = 0
    short_offset_steps: int = 2
    take_profit_pct: float = 0.60
    stop_loss_pct: float = 0.40


class CreditSpreadCfg(BaseModel):
    short_delta_target: float = 0.25
    wing_width_points: int = 50
    take_profit_pct: float = 0.50
    stop_loss_mult: float = 1.75
    fallback_short_offset_steps: int = 3   # used when live greeks/delta missing


class StrategyCfg(BaseModel):
    timeframe_bias_min: int = 15
    timeframe_entry_min: int = 5
    breakout_lookback_bars: int = 6
    iron_condor: IronCondorCfg = IronCondorCfg()
    debit_spread: DebitSpreadCfg = DebitSpreadCfg()
    credit_spread: CreditSpreadCfg = CreditSpreadCfg()


class CostsCfg(BaseModel):
    slippage_points_per_leg: float = 1.0
    brokerage_per_order: float = 20.0
    stt_pct_sell_premium: float = 0.0625
    exchange_txn_pct: float = 0.0503
    gst_pct: float = 18.0
    sebi_per_crore: float = 10.0
    stamp_pct_buy: float = 0.003


class CalendarCfg(BaseModel):
    holidays: list[str] = Field(default_factory=list)
    event_blackout_dates: list[str] = Field(default_factory=list)


class RecorderCfg(BaseModel):
    enabled: bool = True              # master switch; false = recorder never persists
    collect_on_start: bool = False   # initial state of the runtime tick/chain toggle
    chain_snapshot_interval_sec: float = 5
    strikes_each_side: int = 15
    tick_strikes_each_side: int = 5
    batch_flush_rows: int = 2000
    batch_flush_ms: int = 500
    queue_maxsize: int = 100000
    record_future: bool = True


class WarmupCfg(BaseModel):
    enabled: bool = True
    bias_bars_needed: int = 30
    source: str = "auto"


class StorageCfg(BaseModel):
    backend: str = "sqlite"
    db_dir: str = "data/db"
    parquet_dir: str = "data/parquet"
    state_dir: str = "data/state"
    log_dir: str = "data/logs"
    wal: bool = True


class SimCfg(BaseModel):
    speed_factor: float = 60
    tick_interval_ms: int = 250
    start_spot: float = 24000.0
    base_iv: float = 0.14
    risk_free_rate: float = 0.065
    seed: int = 42
    warmup_days: int = 3
    iv_rank_value: float = 55.0    # sim IV-rank (>= high_threshold to exercise credit path)


class ApiCfg(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8081


class UiCfg(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8080
    refresh_interval_sec: float = 2
    engine_state_url: str = "http://127.0.0.1:8081/state"
    command_url: str = "http://127.0.0.1:8081/command"


class NotifyCfg(BaseModel):
    backend: str = "auto"


class Secrets(BaseModel):
    upstox_api_key: Optional[str] = None
    upstox_secret_key: Optional[str] = None
    upstox_access_token: Optional[str] = None
    upstox_redirect_uri: Optional[str] = None
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    command_api_token: str = "change-me-local-token"


class Config(BaseModel):
    mode: Literal["paper", "live"] = "paper"
    simulate_feed: bool = False
    timezone: str = "Asia/Kolkata"
    session: SessionCfg = SessionCfg()
    instrument: InstrumentCfg = InstrumentCfg()
    capital: CapitalCfg = CapitalCfg()
    regime: RegimeCfg = RegimeCfg()
    iv_rank: IVRankCfg = IVRankCfg()
    strategy: StrategyCfg = StrategyCfg()
    costs: CostsCfg = CostsCfg()
    calendar: CalendarCfg = CalendarCfg()
    recorder: RecorderCfg = RecorderCfg()
    warmup: WarmupCfg = WarmupCfg()
    storage: StorageCfg = StorageCfg()
    sim: SimCfg = SimCfg()
    api: ApiCfg = ApiCfg()
    ui: UiCfg = UiCfg()
    notify: NotifyCfg = NotifyCfg()
    secrets: Secrets = Secrets()

    # convenience
    @property
    def is_live_data(self) -> bool:
        return not self.simulate_feed


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_config(path: str | os.PathLike | None = None) -> Config:
    root = _project_root()
    load_dotenv(root / ".env")

    cfg_path = Path(path) if path else root / "config" / "config.yaml"
    raw: dict = {}
    if cfg_path.exists():
        raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}

    secrets = Secrets(
        upstox_api_key=os.getenv("UPSTOX_API_KEY") or None,
        upstox_secret_key=os.getenv("UPSTOX_SECRET_KEY") or None,
        upstox_access_token=os.getenv("UPSTOX_ACCESS_TOKEN") or None,
        upstox_redirect_uri=os.getenv("UPSTOX_REDIRECT_URI") or None,
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID") or None,
        command_api_token=os.getenv("COMMAND_API_TOKEN") or "change-me-local-token",
    )
    raw["secrets"] = secrets.model_dump()
    cfg = Config(**raw)

    # Ensure data dirs exist
    for d in (cfg.storage.db_dir, cfg.storage.parquet_dir,
              cfg.storage.state_dir, cfg.storage.log_dir):
        (root / d).mkdir(parents=True, exist_ok=True)
    return cfg


def project_root() -> Path:
    return _project_root()
