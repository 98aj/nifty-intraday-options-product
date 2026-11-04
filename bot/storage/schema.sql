-- Daily capture DB schema. All times: utc epoch-millis + IST string.
-- One file per trading day (data/db/YYYY-MM-DD.db), WAL mode.

CREATE TABLE IF NOT EXISTS ticks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    exch_ts_ms    INTEGER NOT NULL,
    recv_ts_ms    INTEGER NOT NULL,
    ist           TEXT    NOT NULL,
    instrument    TEXT    NOT NULL,
    symbol        TEXT,
    ltp           REAL,
    ltq           INTEGER,
    atp           REAL,
    volume        INTEGER,
    total_buy_qty INTEGER,
    total_sell_qty INTEGER,
    oi            REAL,
    oi_change     REAL,
    best_bid      REAL,
    best_ask      REAL,
    bid_qty       INTEGER,
    ask_qty       INTEGER,
    depth_json    TEXT
);
CREATE INDEX IF NOT EXISTS ix_ticks_ts ON ticks(recv_ts_ms);
CREATE INDEX IF NOT EXISTS ix_ticks_instr_ts ON ticks(instrument, recv_ts_ms);

CREATE TABLE IF NOT EXISTS chain_snapshots (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_ms      INTEGER NOT NULL,
    ist        TEXT    NOT NULL,
    spot       REAL,
    vix        REAL,
    expiry     TEXT,
    strike     REAL,
    opt_type   TEXT,
    instrument TEXT,
    ltp        REAL,
    bid        REAL,
    ask        REAL,
    bid_qty    INTEGER,
    ask_qty    INTEGER,
    volume     INTEGER,
    oi         REAL,
    oi_change  REAL,
    iv         REAL,
    delta      REAL,
    gamma      REAL,
    theta      REAL,
    vega       REAL,
    rho        REAL
);
CREATE INDEX IF NOT EXISTS ix_chain_ts ON chain_snapshots(ts_ms);
CREATE INDEX IF NOT EXISTS ix_chain_strike_ts ON chain_snapshots(strike, opt_type, ts_ms);

CREATE TABLE IF NOT EXISTS candles (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    instrument TEXT    NOT NULL,
    tf_min     INTEGER NOT NULL,
    start_ms   INTEGER NOT NULL,
    end_ms     INTEGER NOT NULL,
    ist        TEXT,
    open       REAL,
    high       REAL,
    low        REAL,
    close      REAL,
    volume     INTEGER
);
CREATE INDEX IF NOT EXISTS ix_candles_instr_tf_ts ON candles(instrument, tf_min, start_ms);

CREATE TABLE IF NOT EXISTS regime_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_ms      INTEGER NOT NULL,
    ist        TEXT,
    regime     TEXT,
    raw_regime TEXT,
    confidence REAL,
    adx        REAL,
    adx_slope  REAL,
    chop       REAL,
    vix        REAL,
    bias       TEXT,
    reason     TEXT
);
CREATE INDEX IF NOT EXISTS ix_regime_ts ON regime_log(ts_ms);

CREATE TABLE IF NOT EXISTS journal (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_ms      INTEGER NOT NULL,
    ist        TEXT,
    event      TEXT,        -- SIGNAL / RISK / ORDER / FILL / POSITION / INFO
    kind       TEXT,        -- strategy kind
    approved   INTEGER,     -- for RISK events: 1/0
    pnl        REAL,
    detail     TEXT,        -- human text
    payload    TEXT         -- json
);
CREATE INDEX IF NOT EXISTS ix_journal_ts ON journal(ts_ms);
