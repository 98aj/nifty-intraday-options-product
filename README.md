# NIFTY Intraday Options Bot — Phase 1

A headless, non-blocking, **strictly-intraday** NIFTY options bot built on the Upstox
API. It forward-tests on **paper** while precisely **recording all market data from day
one** — that recorded dataset is the foundation for the v2 backtester. The architecture
keeps the engine, the data recorder, and the UI as separate concerns so the UI can never
block trading, and so BANKNIFTY / multi-user / live orders are additive later, not a
rewrite.

> **Phase 1 status:** paper trading + full recording, on either simulated or **live
> Upstox market data**. Live order placement is deliberately stubbed (raises
> `NotImplementedError`). Not assumed profitable — built to *survive* (defined-risk +
> daily loss cap) while you accumulate your own data.

---

## What it does

- **One feed thread** fans ticks out via a **TickBus** to per-instrument queues; each
  instrument trades on its **own worker thread** (so NIFTY can never delay BANKNIFTY
  later), and the **Data Recorder** consumes independently — recording never stalls
  trading and trading never stalls recording.
- **Multi-timeframe regime engine:** builds 5m + 15m candles from ticks. 15m decides
  **regime + bias** (ADX + slope, Choppiness Index, India VIX context → a confidence
  vote with **confirmation + dwell hysteresis** so it can't flip-flop); 5m decides the
  **entry trigger**; it only trades when the two agree. Every decision is logged with its
  factor values and a human-readable reason.
- **Day switch:**
  - **Expiry day** (derived from the live contract list — *not* a fixed weekday, so
    holiday-shifted expiries are handled) → **iron condor** (defined-risk premium
    selling, skipped if VIX is elevated).
  - **Normal day:** TREND → directional **debit spread** on a 5m breakout; RANGE +
    high IV-rank → small **credit spread**; RANGE + normal/low IV, or transition/low
    confidence → **FLAT**.
- **Risk gate (gatekeeper):** nothing reaches execution without passing it — defined-risk
  only (never a naked short), per-trade risk budget (VIX-scaled), **daily max-loss halt**,
  optional profit-target halt, max 1 open position, max trades/day, cost-awareness, event
  blackout, and session timing (no new entries after 14:30, hard square-off 15:00, earlier
  on expiry).
- **Paper execution** with pessimistic slippage and **safe leg ordering** (longs placed
  first on entry, removed last on exit — never briefly naked).
- **Data recorder** runs the whole session **whether or not the strategy is trading**
  (records even when FLAT): ticks (with depth), full option-chain snapshots (greeks/IV as
  Upstox provides — never fabricated), derived candles, the regime log, and the full
  signal/risk/order/fill journal.
- **Storage:** daily SQLite files (WAL + batched inserts) → on-demand **Parquet** export
  (the v2 backtester's format) and **Excel/CSV** export.
- **Control + alerts:** Telegram (console fallback) and a FastAPI webhook, both accepting
  `status / pause / resume / flatten / kill`.
- **UI:** a separate, read-only **NiceGUI** dashboard that reads `/state` and POSTs
  commands to the webhook — it cannot touch engine internals.

---

## Project layout

```
config/config.yaml      all tunables (no magic numbers in code)
.env / .env.example     secrets (Upstox token, Telegram, API token)
bot/
  main.py               engine wiring + control loop
  config.py  clock.py  models.py
  core/                 tickbus, state_store, commands, instrument_worker
  data/                 feed_base, sim_feed, sim_chain, blackscholes,
                        upstox_auth/feed/chain, instruments, candles, warmup
  regime/               indicators (ADX+CHOP, dependency-free fallback),
                        regime_engine, iv_rank
  strategy/             base, strikes, day_switch, iron_condor,
                        debit_spread, credit_spread, exits
  risk/                 risk_manager (gate), sizing, costs, calendar
  execution/            base, paper, live (stub), pnl
  storage/              repository, sqlite_store, schema.sql,
                        parquet_export, excel_export
  recorder/             recorder (independent writer thread)
  notify/               base, console, telegram_bot, factory
  api/                  command_api (FastAPI /state + /command)
  cli.py                exports + status
ui/dashboard.py         NiceGUI read-only dashboard
scripts/                run.py (cross-platform), start.ps1, stop.ps1
tests/                  candles, indicators, hysteresis, risk gate,
                        paper leg-ordering, recorder, end-to-end sim smoke
data/                   db/  parquet/  state/  logs/  exports/  (gitignored)
```

---

## Setup (Windows)

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

> **CPU note:** on hardware without AVX2, install `polars-lts-cpu` instead of `polars`
> (same `import polars`). If you see a Polars CPU warning, that's the fix.

Copy secrets and fill them in:

```bash
copy .env.example .env
```

`.env` keys: `UPSTOX_ACCESS_TOKEN` (extended market-data token is enough for recording +
paper), optional `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`, and `COMMAND_API_TOKEN` (the
bearer token the UI/curl must send).

---

## Run

**Mode switch** is in `config/config.yaml`:

- `simulate_feed: true` → **no token needed**; simulated ticks + simulated option chain.
- `simulate_feed: false` → **live Upstox market data** (recording + paper trading on real
  ticks). `mode: paper` keeps orders simulated; `mode: live` is intentionally not
  implemented yet.

Start engine **and** dashboard (background):

```bash
.venv\Scripts\python.exe scripts\run.py start
```

Or PowerShell: `./scripts/start.ps1` — stop with `./scripts/stop.ps1`.

Run the engine in the **foreground** (Ctrl-C to stop):

```bash
.venv\Scripts\python.exe -m bot.main
```

Run the dashboard alone:

```bash
.venv\Scripts\python.exe -m ui.dashboard
```

- Dashboard: <http://127.0.0.1:8080>
- State API: <http://127.0.0.1:8081/state>  ·  Health: `/health`

### Data collection toggle (default OFF)

Recording of the **high-volume market data (ticks + option-chain snapshots)** starts
**OFF** and is toggled at runtime — from the dashboard ("Rec ON" / "Rec OFF"), Telegram
(`record_on` / `record_off`), or the webhook. The recorder thread and the daily DB stay
alive while off, so toggling resumes instantly. **Candles, the regime log, and the full
trade journal always record** regardless of the toggle, so your audit trail is never lost.
Change the startup default with `recorder.collect_on_start` in `config.yaml`; the master
`recorder.enabled: false` disables the recorder entirely.

### After-hours / live window

In **live** mode the engine only contacts Upstox inside the trading window (~09:00–15:30
IST on a trading day). Started outside it — including after the close or on a holiday — it
logs that the market is closed and exits **without making any Upstox API call**. A running
session already stops polling the chain and shuts down at 15:30. (Sim mode runs anytime.)

### Commands (Telegram or webhook)

Telegram: message the bot `status`, `pause`, `resume`, `flatten`, `kill`,
`record_on`, `record_off` (only your configured chat id is honoured). Webhook:

```bash
curl -X POST http://127.0.0.1:8081/command -H "Authorization: Bearer <COMMAND_API_TOKEN>" -H "Content-Type: application/json" -d "{\"command\":\"status\"}"
```

---

## Data export

```bash
.venv\Scripts\python.exe -m bot.cli days                     # list recorded days
.venv\Scripts\python.exe -m bot.cli export-parquet latest    # SQLite -> partitioned Parquet
.venv\Scripts\python.exe -m bot.cli export-excel  latest     # review workbook (one sheet/table)
.venv\Scripts\python.exe -m bot.cli export-csv    latest     # one CSV per table
.venv\Scripts\python.exe -m bot.cli status                   # live engine snapshot
```

Daily DB files: `data/db/YYYY-MM-DD.db`. Parquet: `data/parquet/<table>/date=<day>/`.

---

## Tests

```bash
.venv\Scripts\python.exe -m pytest -q
```

Covers candle bucketing, ADX/Choppiness (incl. the dependency-free fallback), regime
hysteresis, the risk gate (defined-risk + naked-short rejection + halts), paper leg
ordering (longs-first / shorts-first-out), recorder batching + overflow accounting, and
an **end-to-end sim smoke test** that boots the whole engine with no token and asserts
ticks + chain snapshots are recorded.

---

## Config highlights (`config/config.yaml`)

Everything is tunable: ADX/Choppiness thresholds, confirmation/dwell, IV-rank cutoff,
condor/spread deltas and wings, TP/SL, cost model, recorder cadence (`chain_snapshot_
interval_sec`) and strike windows (`strikes_each_side`, `tick_strikes_each_side`), capital
and daily-loss limits, session times, holidays and event-blackout dates, and the sim
model (speed factor, start spot, IV, seed).

---

## Deliberately deferred (clean boundaries, additive later)

BANKNIFTY, multi-user accounts, **live order placement** (needs the account's static IP +
a daily OAuth token; `LiveExecutor` raises until built on purpose), the **backtesting
engine** (we record now; build it on the Parquet dataset in v2), and the Hurst exponent in
the regime vote.
```

**Mindset:** defined-risk and a daily loss cap are there so the bot *survives* while you
forward-test on paper and accumulate a precise dataset. It is **not** assumed profitable
until validated on that collected data.
