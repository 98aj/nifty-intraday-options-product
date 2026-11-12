"""Read-only NiceGUI dashboard (SEPARATE process) — operations console.

It NEVER touches engine internals: it reads the engine's /state endpoint (served by
the command API) and posts control commands to the /command webhook — the same
commands as Telegram. Because it only reads snapshots and posts commands, it can
never block trading. NiceGUI pushes updates over websocket, so panels refresh live.

Run:  python -m ui.dashboard
"""
from __future__ import annotations

import time
from datetime import datetime

import httpx
from nicegui import ui

from bot.config import load_config

CFG = load_config()
STATE_URL = CFG.ui.engine_state_url
COMMAND_URL = CFG.ui.command_url
TOKEN = CFG.secrets.command_api_token
REFRESH = CFG.ui.refresh_interval_sec

# Async client: all network I/O is awaited so the NiceGUI event loop is never
# blocked (a blocking call here stalls the websocket heartbeat and the browser
# shows "connection lost / trying to reconnect").
_aclient = httpx.AsyncClient(timeout=2.5)
CONFIG_URL = STATE_URL.replace("/state", "/config")

# ---- status -> colour map ----
STATUS_COLOR = {
    "RUNNING": "positive", "STARTING": "info", "PAUSED": "warning",
    "HALTED": "negative", "SQUARED_OFF": "warning", "STOPPED": "grey",
    "WAITING": "info",
}
REGIME_COLOR = {
    "TREND_UP": "positive", "TREND_DOWN": "negative", "RANGE": "info",
    "TRANSITION": "warning", "UNKNOWN": "grey",
}
EVENT_COLOR = {
    "ORDER": "text-blue-400", "FILL": "text-emerald-400", "RISK": "text-amber-400",
    "REGIME": "text-violet-400", "SIGNAL": "text-sky-400", "INFO": "text-gray-400",
}


async def fetch_state() -> dict:
    try:
        r = await _aclient.get(STATE_URL)
        return r.json()
    except Exception:
        return {}


async def send_command(cmd: str) -> None:
    try:
        r = await _aclient.post(COMMAND_URL, json={"command": cmd},
                                headers={"Authorization": f"Bearer {TOKEN}"})
        if r.status_code == 200:
            ui.notify(f"sent: {cmd}", type="positive", position="top")
        else:
            ui.notify(f"{cmd} failed: {r.status_code}", type="negative", position="top")
    except Exception as exc:
        ui.notify(f"command error: {exc}", type="negative", position="top")


async def confirm_command(cmd: str, label: str, danger: bool = True) -> None:
    with ui.dialog() as dialog, ui.card().classes("items-center gap-3 p-6"):
        ui.icon("warning", size="2.5rem").classes(
            "text-red-500" if danger else "text-amber-500")
        ui.label(f"Confirm: {label}?").classes("text-lg font-semibold")
        ui.label("This acts on live positions immediately.").classes(
            "text-sm text-gray-500")
        with ui.row().classes("gap-2 mt-2"):
            ui.button("Cancel", on_click=lambda: dialog.submit(False)).props("flat")
            ui.button(label, on_click=lambda: dialog.submit(True)).props(
                "color=red" if danger else "color=primary")
    if await dialog:
        await send_command(cmd)


async def open_settings() -> None:
    try:
        r = await _aclient.get(CONFIG_URL)
        data = r.json()
    except Exception as exc:
        ui.notify(f"cannot load settings: {exc}", type="negative", position="top")
        return
    schema = data.get("schema", {})
    values = data.get("values", {})
    inputs: dict = {}

    with ui.dialog() as dialog, ui.card().classes("p-5 gap-1 min-w-[400px]"):
        ui.label("Settings").classes("text-lg font-semibold")
        ui.label("Applies live and is saved to config/user_overrides.yaml "
                 "(kept across restarts).").classes("text-xs text-gray-500 mb-1")
        groups: dict = {}
        for k, spec in schema.items():
            groups.setdefault(spec.get("group", "Other"), []).append((k, spec))
        for gname, items in groups.items():
            ui.label(gname).classes("text-xs uppercase text-gray-500 mt-2")
            for k, spec in items:
                inputs[k] = ui.number(
                    label=spec.get("label", k),
                    value=values.get(k),
                    min=spec.get("min"), max=spec.get("max"),
                    format="%.0f" if spec.get("type") == "int" else None,
                ).classes("w-full")
        with ui.row().classes("justify-end gap-2 mt-4 w-full"):
            ui.button("Cancel", on_click=lambda: dialog.submit(False)).props("flat")
            ui.button("Save", on_click=lambda: dialog.submit(True)).props("color=primary")

    if not await dialog:
        return
    updates = {k: inp.value for k, inp in inputs.items() if inp.value is not None}
    try:
        r = await _aclient.post(CONFIG_URL, json={"updates": updates},
                                headers={"Authorization": f"Bearer {TOKEN}"})
        if r.status_code == 200:
            ui.notify("settings saved", type="positive", position="top")
        else:
            ui.notify(f"save failed: {r.status_code} {r.text}", type="negative",
                      position="top")
    except Exception as exc:
        ui.notify(f"save error: {exc}", type="negative", position="top")


def kpi_tile(container, title: str, icon: str):
    """Build a KPI tile; return (value_label, sub_label) for updates."""
    with container:
        with ui.card().classes(
                "flex-1 min-w-[160px] p-4 rounded-xl shadow-sm").style(
                "background:#18181b;border:1px solid #27272a"):
            with ui.row().classes("items-center gap-2 no-wrap"):
                ui.icon(icon).classes("text-gray-400")
                ui.label(title).classes(
                    "text-xs uppercase tracking-wide text-gray-500")
            value = ui.label("—").classes("text-2xl font-bold mt-1")
            sub = ui.label("").classes("text-xs text-gray-500")
    return value, sub


@ui.page("/")
def index():
    ui.dark_mode(True)
    ui.query("body").classes("bg-neutral-50 dark:bg-neutral-950")
    w: dict = {}

    # ---------------- header ----------------
    with ui.header().classes(
            "items-center justify-between px-5 py-3 bg-neutral-900 text-white shadow"):
        with ui.row().classes("items-center gap-3 no-wrap"):
            ui.icon("candlestick_chart", size="1.6rem").classes("text-emerald-400")
            ui.label("NIFTY Options Bot").classes("text-xl font-bold")
            w["mode"] = ui.badge("paper", color="secondary").props("rounded")
        with ui.row().classes("items-center gap-3 no-wrap"):
            w["conn"] = ui.icon("circle", size="0.8rem").classes("text-gray-500")
            w["status"] = ui.badge("…", color="grey").props("rounded").classes(
                "text-sm px-3 py-1")
            w["updated"] = ui.label("").classes("text-xs text-gray-400")
            ui.button(icon="settings", on_click=open_settings).props(
                "flat round color=white").tooltip("Settings (capital, lot, risk)")

    with ui.column().classes("w-full max-w-[1200px] mx-auto p-4 gap-4"):

        # halt banner (hidden unless halted)
        w["halt"] = ui.row().classes(
            "w-full items-center gap-2 p-3 rounded-lg bg-red-100 "
            "dark:bg-red-950 text-red-700 dark:text-red-300")
        with w["halt"]:
            ui.icon("report")
            w["halt_text"] = ui.label("")
        w["halt"].visible = False

        # ---------------- KPI tiles ----------------
        tiles = ui.row().classes("w-full gap-3 flex-wrap")
        w["pnl"], w["pnl_sub"] = kpi_tile(tiles, "P&L Today", "payments")
        w["spot"], w["spot_sub"] = kpi_tile(tiles, "NIFTY", "trending_up")
        w["vix"], w["vix_sub"] = kpi_tile(tiles, "India VIX", "bolt")
        w["trades"], w["trades_sub"] = kpi_tile(tiles, "Trades", "receipt_long")
        w["rec"], w["rec_sub"] = kpi_tile(tiles, "Recording", "fiber_manual_record")

        # ---------------- main grid ----------------
        with ui.row().classes("w-full gap-4 flex-wrap items-stretch"):

            # LEFT column: chart + position + journal
            with ui.column().classes("flex-[2] min-w-[360px] gap-4"):
                with ui.card().classes("w-full p-4 rounded-xl"):
                    with ui.row().classes("items-center justify-between w-full"):
                        ui.label("NIFTY — recent 5m closes").classes(
                            "text-sm font-semibold text-gray-500")
                        w["strategy"] = ui.badge("—", color="secondary").props("rounded")
                    w["chart"] = ui.echart({
                        "xAxis": {"type": "category", "data": []},
                        "yAxis": {"type": "value", "scale": True},
                        "grid": {"left": 48, "right": 16, "top": 16, "bottom": 28},
                        "tooltip": {"trigger": "axis"},
                        "series": [{"type": "line", "data": [], "smooth": True,
                                    "showSymbol": False,
                                    "lineStyle": {"width": 2, "color": "#34d399"},
                                    "areaStyle": {"color": "rgba(52,211,153,0.12)"}}],
                    }).classes("w-full h-56")

                with ui.card().classes("w-full p-4 rounded-xl"):
                    with ui.row().classes("items-center justify-between w-full"):
                        ui.label("Open Position").classes("text-base font-semibold")
                        w["pos_badge"] = ui.badge("FLAT", color="grey").props("rounded")
                    w["pos_summary"] = ui.label("No open position.").classes(
                        "text-sm text-gray-500 mt-1")
                    # TP / SL progress
                    with ui.column().classes("w-full gap-1 mt-2"):
                        w["tpsl_label"] = ui.label("").classes("text-xs text-gray-500")
                        w["tpsl"] = ui.linear_progress(value=0.5, show_value=False,
                                                       size="14px").classes("w-full")
                    w["pos_table"] = ui.table(columns=[
                        {"name": "symbol", "label": "Leg", "field": "symbol",
                         "align": "left"},
                        {"name": "side", "label": "Side", "field": "side"},
                        {"name": "strike", "label": "Strike", "field": "strike"},
                        {"name": "qty", "label": "Qty", "field": "qty"},
                        {"name": "entry_price", "label": "Entry", "field": "entry_price"},
                    ], rows=[], row_key="symbol").classes("w-full mt-2").props("dense flat")

                with ui.card().classes("w-full p-4 rounded-xl"):
                    with ui.row().classes("items-center justify-between w-full"):
                        ui.label("Today's Trades").classes("text-base font-semibold")
                        w["trades_count"] = ui.badge("0", color="secondary").props(
                            "rounded")
                    w["trades_table"] = ui.table(columns=[
                        {"name": "exit_ist", "label": "Closed", "field": "exit_ist",
                         "align": "left"},
                        {"name": "kind", "label": "Strategy", "field": "kind",
                         "align": "left"},
                        {"name": "legs", "label": "Legs", "field": "legs"},
                        {"name": "entry_net", "label": "Entry net", "field": "entry_net"},
                        {"name": "pnl", "label": "P&L ₹", "field": "pnl"},
                        {"name": "risk", "label": "Risk ₹", "field": "risk"},
                        {"name": "reason", "label": "Exit reason", "field": "reason",
                         "align": "left"},
                    ], rows=[], row_key="exit_ist").classes("w-full mt-2").props(
                        "dense flat")
                    w["trades_empty"] = ui.label("No closed trades yet today.").classes(
                        "text-sm text-gray-500 mt-1")

                with ui.card().classes("w-full p-4 rounded-xl"):
                    ui.label("Activity Journal").classes("text-base font-semibold")
                    w["journal"] = ui.column().classes(
                        "w-full gap-0.5 mt-2 text-xs font-mono max-h-64 overflow-auto")

            # RIGHT column: regime + recorder + controls
            with ui.column().classes("flex-1 min-w-[300px] gap-4"):
                with ui.card().classes("w-full p-4 rounded-xl"):
                    with ui.row().classes("items-center justify-between w-full"):
                        ui.label("Market Regime").classes("text-base font-semibold")
                        w["regime_badge"] = ui.badge("—", color="grey").props("rounded")
                    with ui.column().classes("w-full gap-1 mt-2"):
                        ui.label("Confidence").classes("text-xs text-gray-500")
                        w["conf"] = ui.linear_progress(value=0.0, show_value=False,
                                                       size="16px").classes("w-full")
                        w["conf_val"] = ui.label("—").classes("text-xs text-gray-500")
                    with ui.grid(columns=2).classes("w-full gap-2 mt-3"):
                        w["adx"] = _metric("ADX")
                        w["chop"] = _metric("Choppiness")
                        w["bias"] = _metric("Bias")
                        w["ivr"] = _metric("IV-rank")
                    w["regime_reason"] = ui.label("").classes(
                        "text-xs text-gray-500 mt-2 leading-snug")

                # ---- Decision pipeline: what the bot is thinking ----
                with ui.card().classes("w-full p-4 rounded-xl"):
                    with ui.row().classes("items-center justify-between w-full"):
                        ui.label("Decision").classes("text-base font-semibold")
                        w["dec_badge"] = ui.badge("—", color="grey").props(
                            "rounded")
                    with ui.column().classes("w-full gap-2 mt-2"):
                        for key, title in (("dec_regime", "REGIME"),
                                           ("dec_strategy", "STRATEGY"),
                                           ("dec_risk", "RISK"),
                                           ("dec_action", "ACTION")):
                            with ui.row().classes("items-start gap-2 no-wrap w-full"):
                                ui.label(title).classes(
                                    "text-[10px] uppercase tracking-wide "
                                    "text-gray-500 w-16 mt-0.5 shrink-0")
                                if key == "dec_strategy":
                                    with ui.column().classes("gap-0 min-w-0"):
                                        w["dec_strategy"] = ui.label("—").classes(
                                            "text-sm font-semibold")
                                        w["dec_reason"] = ui.label("").classes(
                                            "text-xs text-gray-500 leading-snug")
                                else:
                                    w[key] = ui.label("—").classes("text-sm")

                with ui.card().classes("w-full p-4 rounded-xl"):
                    with ui.row().classes("items-center justify-between w-full"):
                        ui.label("Data Recorder").classes("text-base font-semibold")
                        w["rec_badge"] = ui.badge("OFF", color="grey").props("rounded")
                    with ui.grid(columns=2).classes("w-full gap-2 mt-2"):
                        w["rec_ticks"] = _metric("Ticks")
                        w["rec_chain"] = _metric("Chain snaps")
                        w["rec_drop"] = _metric("Dropped")
                        w["rec_q"] = _metric("Queue")
                    w["rec_db"] = ui.label("").classes(
                        "text-[10px] text-gray-500 break-all mt-1")

                with ui.card().classes("w-full p-4 rounded-xl gap-3"):
                    ui.label("Controls").classes("text-base font-semibold")
                    ui.label("Trading").classes("text-xs uppercase text-gray-500")
                    with ui.row().classes("gap-2 flex-wrap"):
                        ui.button("Pause", icon="pause",
                                  on_click=lambda: send_command("pause")
                                  ).props("color=amber outline")
                        ui.button("Resume", icon="play_arrow",
                                  on_click=lambda: send_command("resume")
                                  ).props("color=green outline")
                        ui.button("Flatten", icon="close",
                                  on_click=lambda: confirm_command("flatten", "Flatten")
                                  ).props("color=red outline")
                        ui.button("Kill", icon="power_settings_new",
                                  on_click=lambda: confirm_command("kill", "Kill switch")
                                  ).props("color=red")
                    ui.separator()
                    ui.label("Data collection").classes(
                        "text-xs uppercase text-gray-500")
                    with ui.row().classes("gap-2 items-center flex-wrap"):
                        ui.button("Rec ON", icon="fiber_manual_record",
                                  on_click=lambda: send_command("record_on")
                                  ).props("color=blue")
                        ui.button("Rec OFF", icon="stop",
                                  on_click=lambda: send_command("record_off")
                                  ).props("color=grey outline")
                        ui.button(icon="refresh",
                                  on_click=lambda: send_command("status")
                                  ).props("flat round").tooltip("Ping status")
                    ui.separator()
                    ui.label("Execution mode").classes(
                        "text-xs uppercase text-gray-500")
                    with ui.row().classes("gap-2 items-center flex-wrap"):
                        w["btn_paper"] = ui.button(
                            "Paper", icon="description",
                            on_click=lambda: send_command("mode_paper"))
                        w["btn_live"] = ui.button(
                            "Live", icon="bolt",
                            on_click=lambda: confirm_command(
                                "mode_live",
                                "Switch to LIVE (orders not yet enabled)")
                            ).props("outline color=red")
                    ui.label("Live orders are not implemented in Phase 1; "
                             "LIVE is safe-stubbed.").classes(
                        "text-[10px] text-gray-500")

    # ---------------- refresh loop ----------------
    async def refresh():
        s = await fetch_state()
        if not s:
            w["conn"].classes(replace="text-red-500")
            w["status"].text = "DISCONNECTED"
            w["status"].props("color=negative")
            return
        w["conn"].classes(replace="text-emerald-500")

        status = s.get("status", "—")
        w["status"].text = status
        w["status"].props(f"color={STATUS_COLOR.get(status, 'grey')}")
        w["mode"].text = (f"{s.get('mode','paper')}"
                          f"{' · SIM' if s.get('simulate_feed') else ' · LIVE'}"
                          f"{' · EXPIRY' if s.get('is_expiry_day') else ''}")
        upd = s.get("updated_ms", 0)
        if upd:
            age = max(0, time.time() - upd / 1000.0)
            w["updated"].text = f"updated {age:.0f}s ago"

        halted = s.get("halted_reason")
        w["halt"].visible = bool(halted)
        if halted:
            w["halt_text"].text = f"HALTED — {halted}"

        # KPIs
        pnl = s.get("pnl_day") or 0.0
        w["pnl"].text = f"₹{pnl:,.0f}"
        w["pnl"].classes(replace="text-2xl font-bold mt-1 "
                         + ("text-emerald-500" if pnl >= 0 else "text-red-500"))
        w["pnl_sub"].text = f"realized ₹{s.get('realized_pnl_day', 0):,.0f}"
        u = s.get("underlying", {})
        w["spot"].text = f"{(u.get('ltp') or 0):,.1f}"
        vix = s.get("vix") or 0.0
        w["vix"].text = f"{vix:,.2f}"
        w["vix_sub"].text = "elevated" if vix >= 16 else "calm"
        w["trades"].text = str(s.get("trades_today", 0))
        w["trades_sub"].text = s.get("strategy_today") or "—"

        rec = s.get("recorder", {})
        collecting = rec.get("collecting")
        w["rec"].text = "ON" if collecting else "OFF"
        w["rec"].classes(replace="text-2xl font-bold mt-1 "
                         + ("text-emerald-500" if collecting else "text-gray-500"))
        w["rec_sub"].text = f"{(rec.get('ticks') or 0):,} ticks"
        w["rec_badge"].text = "ON" if collecting else "OFF"
        w["rec_badge"].props(f"color={'positive' if collecting else 'grey'}")
        _set(w["rec_ticks"], f"{(rec.get('ticks') or 0):,}")
        _set(w["rec_chain"], f"{(rec.get('chain_snaps') or 0):,}")
        _set(w["rec_drop"], str(rec.get("dropped", 0)))
        _set(w["rec_q"], str(rec.get("queue_depth", 0)))
        w["rec_db"].text = rec.get("db_file") or ""

        # strategy badge
        w["strategy"].text = s.get("strategy_today") or "—"

        # regime
        reg = s.get("regime") or {}
        rg = reg.get("regime", "UNKNOWN")
        w["regime_badge"].text = rg.replace("_", " ")
        w["regime_badge"].props(f"color={REGIME_COLOR.get(rg, 'grey')}")
        conf = reg.get("confidence") or 0.0
        w["conf"].value = float(conf)
        w["conf_val"].text = f"{conf:.0%}"
        _set(w["adx"], f"{reg.get('adx', '—')}")
        _set(w["chop"], f"{reg.get('chop', '—')}")
        _set(w["bias"], reg.get("bias", "—"))
        w["regime_reason"].text = reg.get("reason", "")

        # decision pipeline — what the bot is thinking
        dec = s.get("decision") or {}
        ivr = dec.get("iv_rank")
        _set(w["ivr"], f"{ivr:.0f}" if isinstance(ivr, (int, float)) else "—")
        drg = dec.get("regime", "UNKNOWN")
        w["dec_regime"].text = f"{drg.replace('_', ' ')} · {(dec.get('confidence') or 0.0):.0%}"
        dkind = dec.get("kind") or ""
        w["dec_strategy"].text = dkind.replace("_", " ") if dkind else "—"
        w["dec_reason"].text = dec.get("kind_reason") or ""
        approved = dec.get("approved")
        if approved is None:
            w["dec_risk"].text = "—"
            w["dec_risk"].classes(replace="text-sm text-gray-400")
        elif approved:
            w["dec_risk"].text = (
                f"✓ approved · risk ₹{(dec.get('max_risk') or 0):,.0f} · "
                f"reward ₹{(dec.get('max_reward') or 0):,.0f} · "
                f"costs ₹{(dec.get('est_costs') or 0):,.0f}")
            w["dec_risk"].classes(replace="text-sm text-emerald-500")
        else:
            w["dec_risk"].text = f"✗ blocked: {dec.get('risk_note') or ''}"
            w["dec_risk"].classes(replace="text-sm text-red-400")
        action = dec.get("action") or "—"
        w["dec_action"].text = action
        al = action.lower()
        if any(x in al for x in ("approved", "opening", "in position")):
            bc = "positive"
        elif any(x in al for x in ("blocked", "halt")):
            bc = "negative"
        elif "paused" in al:
            bc = "warning"
        else:
            bc = "grey"
        w["dec_badge"].text = (action[:20] + "…") if len(action) > 21 else action
        w["dec_badge"].props(f"color={bc}")

        # position
        pos = s.get("position")
        if pos and pos.get("open"):
            k = pos.get("kind", "")
            w["pos_badge"].text = k.replace("_", " ")
            w["pos_badge"].props("color=primary")
            ppnl = pos.get("pnl") or 0.0
            w["pos_summary"].text = (
                f"entry net ₹{pos.get('entry_net', 0):,.0f} · P&L ₹{ppnl:,.0f} · "
                f"risk ₹{pos.get('max_risk', 0):,.0f} · reward "
                f"₹{pos.get('max_reward', 0):,.0f}")
            w["pos_table"].rows = pos.get("legs", [])
            # TP/SL progress: map pnl between SL (0) and TP (1)
            tp = pos.get("take_profit_level") or 0.0
            sl = pos.get("stop_loss_level") or 0.0
            if tp > sl:
                frac = (ppnl - sl) / (tp - sl)
                w["tpsl"].value = min(1.0, max(0.0, frac))
            w["tpsl_label"].text = (f"SL ₹{sl:,.0f}  ◀  P&L ₹{ppnl:,.0f}  ▶  "
                                    f"TP ₹{tp:,.0f}")
        else:
            w["pos_badge"].text = "FLAT"
            w["pos_badge"].props("color=grey")
            w["pos_summary"].text = "No open position."
            w["pos_table"].rows = []
            w["tpsl"].value = 0.0
            w["tpsl_label"].text = ""

        # chart from recent 5m candles
        candles = s.get("candles_5m") or []
        if candles:
            xs = [datetime.fromtimestamp(c["start_ms"] / 1000).strftime("%H:%M")
                  for c in candles]
            ys = [round(c["close"], 1) for c in candles]
            w["chart"].options["xAxis"]["data"] = xs
            w["chart"].options["series"][0]["data"] = ys
            w["chart"].update()

        # mode toggle highlight
        mode = s.get("mode", "paper")
        w["btn_paper"].props("color=green" if mode == "paper"
                             else "outline color=grey")
        w["btn_live"].props("color=red" if mode == "live"
                            else "outline color=red")

        # trades table
        trades = s.get("trades") or []
        w["trades_count"].text = str(len(trades))
        w["trades_empty"].visible = (len(trades) == 0)
        w["trades_table"].rows = list(reversed(trades))

        # journal
        w["journal"].clear()
        with w["journal"]:
            for line in reversed(s.get("journal_tail", [])[-18:]):
                evt = line.split(" ", 1)[0]
                ui.label(line).classes(EVENT_COLOR.get(evt, "text-gray-400"))

    ui.timer(REFRESH, refresh)


def _metric(title: str):
    with ui.column().classes("gap-0"):
        ui.label(title).classes("text-[10px] uppercase tracking-wide text-gray-500")
        val = ui.label("—").classes("text-sm font-semibold")
    return val


def _set(label, text: str) -> None:
    label.text = text


def run() -> None:
    ui.run(host=CFG.ui.host, port=CFG.ui.port, title="NIFTY Bot Dashboard",
           reload=False, show=False, dark=True)


if __name__ in {"__main__", "__mp_main__"}:
    run()
