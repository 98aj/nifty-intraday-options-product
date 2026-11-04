"""Read-only NiceGUI dashboard (SEPARATE process).

It NEVER touches engine internals: it reads the engine's /state endpoint (served by
the command API) and posts control commands to the /command webhook — the same
commands as Telegram. Because it only reads snapshots and posts commands, it can
never block trading. NiceGUI pushes updates over websocket, so panels refresh live.

Run:  python -m ui.dashboard
"""
from __future__ import annotations

import httpx
from nicegui import ui

from bot.config import load_config

CFG = load_config()
STATE_URL = CFG.ui.engine_state_url
COMMAND_URL = CFG.ui.command_url
TOKEN = CFG.secrets.command_api_token
REFRESH = CFG.ui.refresh_interval_sec

_client = httpx.Client(timeout=4.0)


def fetch_state() -> dict:
    try:
        return _client.get(STATE_URL).json()
    except Exception:
        return {}


def send_command(cmd: str) -> None:
    try:
        r = _client.post(COMMAND_URL, json={"command": cmd},
                         headers={"Authorization": f"Bearer {TOKEN}"})
        if r.status_code == 200:
            ui.notify(f"sent: {cmd}", type="positive")
        else:
            ui.notify(f"{cmd} failed: {r.status_code} {r.text}", type="negative")
    except Exception as exc:
        ui.notify(f"command error: {exc}", type="negative")


@ui.page("/")
def index():
    ui.label("NIFTY Options Bot — Dashboard").classes("text-2xl font-bold")
    ui.label("read-only · reads /state · commands POST to the webhook").classes(
        "text-sm text-gray-500")

    with ui.row().classes("w-full gap-4"):
        status_card = ui.card().classes("min-w-[320px]")
        with status_card:
            ui.label("Engine").classes("text-lg font-semibold")
            lbl_status = ui.label("…")
            lbl_mode = ui.label("")
            lbl_under = ui.label("")
            lbl_vix = ui.label("")
            lbl_pnl = ui.label("")
            lbl_trades = ui.label("")

        regime_card = ui.card().classes("min-w-[320px]")
        with regime_card:
            ui.label("Regime").classes("text-lg font-semibold")
            lbl_regime = ui.label("…")
            lbl_conf = ui.label("")
            lbl_factors = ui.label("")

        rec_card = ui.card().classes("min-w-[320px]")
        with rec_card:
            ui.label("Recorder").classes("text-lg font-semibold")
            lbl_collecting = ui.label("collecting: …").classes("text-base font-bold")
            lbl_ticks = ui.label("")
            lbl_chain = ui.label("")
            lbl_drop = ui.label("")
            lbl_db = ui.label("").classes("text-xs break-all")

    with ui.card().classes("w-full"):
        ui.label("Open position").classes("text-lg font-semibold")
        lbl_pos = ui.label("flat")
        pos_table = ui.table(columns=[
            {"name": "symbol", "label": "leg", "field": "symbol"},
            {"name": "side", "label": "side", "field": "side"},
            {"name": "strike", "label": "strike", "field": "strike"},
            {"name": "qty", "label": "qty", "field": "qty"},
            {"name": "entry", "label": "entry", "field": "entry_price"},
        ], rows=[]).classes("w-full")

    with ui.card().classes("w-full"):
        ui.label("Journal (recent)").classes("text-lg font-semibold")
        journal_box = ui.column().classes("w-full text-sm font-mono")

    with ui.row().classes("gap-2 items-center"):
        ui.label("Trading:").classes("font-semibold")
        ui.button("Pause", on_click=lambda: send_command("pause")).props("color=orange")
        ui.button("Resume", on_click=lambda: send_command("resume")).props("color=green")
        ui.button("Flatten", on_click=lambda: send_command("flatten")).props("color=red")
        ui.button("Kill", on_click=lambda: send_command("kill")).props("color=black")
        ui.button("Status", on_click=lambda: send_command("status"))

    with ui.row().classes("gap-2 items-center"):
        ui.label("Data collection:").classes("font-semibold")
        ui.button("Rec ON", on_click=lambda: send_command("record_on")).props("color=blue")
        ui.button("Rec OFF", on_click=lambda: send_command("record_off")).props("color=grey")

    def refresh():
        s = fetch_state()
        if not s:
            lbl_status.text = "engine unreachable"
            return
        lbl_status.text = f"status: {s.get('status')}"
        lbl_mode.text = (f"mode: {s.get('mode')} · sim: {s.get('simulate_feed')} · "
                         f"expiry: {s.get('is_expiry_day')} · "
                         f"strategy: {s.get('strategy_today')}")
        u = s.get("underlying", {})
        lbl_under.text = f"NIFTY: {u.get('ltp')}"
        lbl_vix.text = f"India VIX: {s.get('vix')}"
        lbl_pnl.text = f"P&L today: {s.get('pnl_day')}"
        lbl_trades.text = f"trades: {s.get('trades_today')} · halted: {s.get('halted_reason')}"

        reg = s.get("regime") or {}
        lbl_regime.text = f"{reg.get('regime', '—')}  (raw {reg.get('raw_regime','—')})"
        lbl_conf.text = f"confidence: {reg.get('confidence', '—')} · bias {reg.get('bias','—')}"
        lbl_factors.text = (f"ADX {reg.get('adx','—')} (slope {reg.get('adx_slope','—')}) · "
                            f"CHOP {reg.get('chop','—')} · VIX {reg.get('vix','—')}")

        rec = s.get("recorder", {})
        collecting = rec.get("collecting")
        lbl_collecting.text = f"collecting: {'ON' if collecting else 'OFF'}"
        lbl_collecting.classes(replace="text-base font-bold "
                               + ("text-green-600" if collecting else "text-red-600"))
        lbl_ticks.text = f"ticks: {rec.get('ticks'):,}" if rec.get('ticks') is not None else "ticks: —"
        lbl_chain.text = f"chain snaps: {rec.get('chain_snaps')}"
        lbl_drop.text = f"dropped: {rec.get('dropped')} · queue: {rec.get('queue_depth')}"
        lbl_db.text = f"db: {rec.get('db_file')}"

        pos = s.get("position")
        if pos and pos.get("open"):
            lbl_pos.text = (f"{pos['kind']} · entry net {pos.get('entry_net'):.1f} · "
                            f"pnl {pos.get('pnl'):.1f} · risk {pos.get('max_risk'):.0f}")
            pos_table.rows = pos.get("legs", [])
        else:
            lbl_pos.text = "flat"
            pos_table.rows = []

        journal_box.clear()
        with journal_box:
            for line in reversed(s.get("journal_tail", [])[-15:]):
                ui.label(line)

    ui.timer(REFRESH, refresh)


def run() -> None:
    ui.run(host=CFG.ui.host, port=CFG.ui.port, title="NIFTY Bot Dashboard",
           reload=False, show=False)


# NiceGUI requires ui.run() at module import time when run as a script/module.
if __name__ in {"__main__", "__mp_main__"}:
    run()
