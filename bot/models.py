"""Shared immutable-ish dataclasses passed between engine components."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional


class OptionType(str, Enum):
    CE = "CE"
    PE = "PE"


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class Regime(str, Enum):
    TREND_UP = "TREND_UP"
    TREND_DOWN = "TREND_DOWN"
    RANGE = "RANGE"
    TRANSITION = "TRANSITION"
    UNKNOWN = "UNKNOWN"


class EngineStatus(str, Enum):
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    HALTED = "HALTED"        # daily loss/profit halt, or kill
    SQUARED_OFF = "SQUARED_OFF"
    STOPPED = "STOPPED"
    WAITING = "WAITING"      # live supervisor idle: market closed, awaiting open


class StrategyKind(str, Enum):
    IRON_CONDOR = "IRON_CONDOR"
    DEBIT_SPREAD = "DEBIT_SPREAD"
    CREDIT_SPREAD = "CREDIT_SPREAD"
    FLAT = "FLAT"


@dataclass
class DepthLevel:
    price: float
    qty: int


@dataclass
class Tick:
    instrument_key: str
    symbol: str
    ltp: float
    exch_ts_ms: int           # exchange timestamp
    recv_ts_ms: int           # local receive timestamp
    ltq: int = 0
    atp: float = 0.0
    volume: int = 0
    total_buy_qty: int = 0
    total_sell_qty: int = 0
    oi: float = 0.0
    oi_change: float = 0.0
    bids: list[DepthLevel] = field(default_factory=list)
    asks: list[DepthLevel] = field(default_factory=list)

    @property
    def best_bid(self) -> float:
        return self.bids[0].price if self.bids else 0.0

    @property
    def best_ask(self) -> float:
        return self.asks[0].price if self.asks else 0.0

    @property
    def mid(self) -> float:
        bb, ba = self.best_bid, self.best_ask
        if bb and ba:
            return (bb + ba) / 2.0
        return self.ltp


@dataclass
class OptionQuote:
    expiry: str               # YYYY-MM-DD
    strike: float
    opt_type: OptionType
    instrument_key: str
    ltp: float
    bid: float = 0.0
    ask: float = 0.0
    bid_qty: int = 0
    ask_qty: int = 0
    volume: int = 0
    oi: float = 0.0
    oi_change: float = 0.0
    iv: Optional[float] = None
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None
    rho: Optional[float] = None

    @property
    def mid(self) -> float:
        if self.bid and self.ask:
            return (self.bid + self.ask) / 2.0
        return self.ltp


@dataclass
class ChainSnapshot:
    ts_ms: int
    spot: float
    vix: float
    expiry: str
    quotes: list[OptionQuote] = field(default_factory=list)

    def atm_strike(self, step: int) -> float:
        return round(self.spot / step) * step

    def get(self, strike: float, opt: OptionType) -> Optional[OptionQuote]:
        for q in self.quotes:
            if q.strike == strike and q.opt_type == opt:
                return q
        return None


@dataclass
class Candle:
    instrument_key: str
    tf_min: int               # 5 or 15
    start_ms: int
    end_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: int = 0
    closed: bool = False


@dataclass
class RegimeDecision:
    ts_ms: int
    regime: Regime
    confidence: float
    adx: float
    adx_slope: float
    chop: float
    vix: float
    bias: str                 # UP / DOWN / NEUTRAL
    reason: str
    raw_regime: Regime = Regime.UNKNOWN   # pre-hysteresis vote this bar


@dataclass
class Leg:
    instrument_key: str
    symbol: str
    opt_type: OptionType
    strike: float
    side: Side
    qty: int                  # absolute contracts (lots * lot_size)
    entry_price: float = 0.0
    exit_price: float = 0.0


@dataclass
class OrderIntent:
    """What the strategy wants; must pass the risk gate before execution."""
    kind: StrategyKind
    legs: list[Leg]
    expiry: str
    max_risk: float
    max_reward: float
    credit: float = 0.0       # net credit (>0) or debit (<0 stored as negative)
    reason: str = ""
    tag: str = ""


@dataclass
class Position:
    kind: StrategyKind
    legs: list[Leg]
    expiry: str
    entry_ts_ms: int
    entry_net: float          # net premium at entry (credit +, debit -)
    max_risk: float
    max_reward: float
    take_profit_pct: float
    stop_loss_level: float    # absolute pnl loss threshold (negative)
    take_profit_level: float  # absolute pnl profit threshold (positive)
    tag: str = ""
    entry_costs: float = 0.0
    current_net: float = 0.0
    pnl: float = 0.0           # unrealized gross-of-exit, net-of-entry-cost
    open: bool = True
    exit_ts_ms: int = 0
    exit_reason: str = ""
    realized: float = 0.0


def to_jsonable(obj) -> dict:
    """Dataclass -> plain dict with enums as their values (for JSON state)."""
    def _conv(v):
        if isinstance(v, Enum):
            return v.value
        if isinstance(v, list):
            return [_conv(x) for x in v]
        if hasattr(v, "__dataclass_fields__"):
            return {k: _conv(val) for k, val in asdict(v).items()}
        return v
    return _conv(obj)
