"""Cross-platform start/stop/status for the engine + dashboard.

  python scripts/run.py start           # start engine + UI (background), health-check
  python scripts/run.py start --sim     # same, but force simulated feed (no token)
  python scripts/run.py start-fg        # run engine in the foreground (Ctrl-C to stop)
  python scripts/run.py start-fg --sim
  python scripts/run.py stop
  python scripts/run.py status

One command brings up BOTH processes. PID files live in data/state/; logs in
data/logs/. Uses the current Python interpreter (the venv one via start.ps1).
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot.config import load_config  # noqa: E402

STATE = ROOT / "data" / "state"
LOGS = ROOT / "data" / "logs"
STATE.mkdir(parents=True, exist_ok=True)
LOGS.mkdir(parents=True, exist_ok=True)
PY = sys.executable

CFG = load_config()
API_URL = f"http://{CFG.api.host}:{CFG.api.port}"
UI_URL = f"http://{CFG.ui.host}:{CFG.ui.port}"

PROCS = {
    "engine": [PY, "-m", "bot.main"],
    "ui": [PY, "-m", "ui.dashboard"],
}


def _pidfile(name: str) -> Path:
    return STATE / f"{name}.pid"


def _alive(pid: int) -> bool:
    try:
        if os.name == "nt":
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                                 capture_output=True, text=True)
            return str(pid) in out.stdout
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _child_env(sim: bool) -> dict:
    env = os.environ.copy()
    # This CPU / many VMs need the compat flag; harmless with polars-lts-cpu.
    env.setdefault("POLARS_SKIP_CPU_CHECK", "1")
    if sim:
        env["BOT_SIMULATE_FEED"] = "true"
    return env


def _http_ok(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return 200 <= r.status < 500
    except Exception:
        return False


def _wait_up(url: str, seconds: float = 15.0) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if _http_ok(url):
            return True
        time.sleep(0.5)
    return False


def start(background: bool = True, sim: bool = False) -> None:
    env = _child_env(sim)
    for name, cmd in PROCS.items():
        pf = _pidfile(name)
        if pf.exists() and _alive(int(pf.read_text() or "0")):
            print(f"{name} already running (pid {pf.read_text()})")
            continue
        creation = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        log = open(LOGS / f"{name}.log", "a", buffering=1)
        p = subprocess.Popen(cmd, cwd=str(ROOT), stdout=log,
                             stderr=subprocess.STDOUT, env=env,
                             creationflags=creation)
        pf.write_text(str(p.pid))
        print(f"started {name} (pid {p.pid}) -> data/logs/{name}.log")
        time.sleep(0.5)

    print(f"\nmode: {'SIMULATED feed' if sim else 'config (' + ('sim' if CFG.simulate_feed else 'live') + ')'}")
    print("waiting for services to come up ...")
    ui_ok = _wait_up(UI_URL, 15)
    eng_ok = _wait_up(API_URL + "/health", 15)
    print(f"  dashboard {UI_URL}  -> {'UP' if ui_ok else 'not responding'}")
    print(f"  state API {API_URL}/state -> {'UP' if eng_ok else 'not responding'}")
    if not eng_ok:
        print("  note: in live mode the engine runs continuously (idle when the "
              "market is closed), so /health may read 'not responding' only for a "
              "moment at startup. Check data/logs/engine.log. Use 'start --sim' to "
              "run a simulated session any time.")
    print("\nOpen the dashboard: " + UI_URL)


def start_fg(sim: bool = False) -> None:
    if sim:
        os.environ["BOT_SIMULATE_FEED"] = "true"
    os.environ.setdefault("POLARS_SKIP_CPU_CHECK", "1")
    from bot.main import main
    main()


def stop() -> None:
    for name in PROCS:
        pf = _pidfile(name)
        if not pf.exists():
            print(f"{name}: no pid file")
            continue
        pid = int(pf.read_text() or "0")
        if pid and _alive(pid):
            try:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                                   capture_output=True)
                else:
                    os.kill(pid, signal.SIGTERM)
                print(f"stopped {name} (pid {pid})")
            except Exception as exc:
                print(f"could not stop {name}: {exc}")
        else:
            print(f"{name}: not running")
        pf.unlink(missing_ok=True)


def status() -> None:
    for name in PROCS:
        pf = _pidfile(name)
        if pf.exists():
            pid = int(pf.read_text() or "0")
            print(f"{name}: {'running' if _alive(pid) else 'stale'} (pid {pid})")
        else:
            print(f"{name}: stopped")
    print(f"dashboard {UI_URL} -> {'UP' if _http_ok(UI_URL) else 'down'}")
    print(f"state API {API_URL}/health -> {'UP' if _http_ok(API_URL + '/health') else 'down'}")


if __name__ == "__main__":
    args = sys.argv[1:]
    action = args[0] if args else "status"
    sim = "--sim" in args
    if action == "start":
        start(True, sim)
    elif action == "start-fg":
        start_fg(sim)
    elif action == "stop":
        stop()
    else:
        status()
