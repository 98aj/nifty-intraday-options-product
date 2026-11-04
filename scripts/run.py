"""Cross-platform start/stop/status for the engine + dashboard.

  python scripts/run.py start      # start engine + UI (background)
  python scripts/run.py start-fg   # start engine in the foreground (Ctrl-C to stop)
  python scripts/run.py stop
  python scripts/run.py status

PID files live in data/state/. Uses the current Python interpreter.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "data" / "state"
STATE.mkdir(parents=True, exist_ok=True)
PY = sys.executable

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


def start(background: bool = True) -> None:
    for name, cmd in PROCS.items():
        pf = _pidfile(name)
        if pf.exists() and _alive(int(pf.read_text() or "0")):
            print(f"{name} already running (pid {pf.read_text()})")
            continue
        creation = 0
        if os.name == "nt":
            creation = subprocess.CREATE_NEW_PROCESS_GROUP
        log = open(ROOT / "data" / "logs" / f"{name}.log", "a", buffering=1)
        p = subprocess.Popen(cmd, cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT,
                             creationflags=creation if os.name == "nt" else 0)
        pf.write_text(str(p.pid))
        print(f"started {name} (pid {p.pid}) -> data/logs/{name}.log")
        time.sleep(1.0)
    print("UI: http://127.0.0.1:8080   API: http://127.0.0.1:8081/state")


def start_fg() -> None:
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


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "status"
    {"start": lambda: start(True), "start-fg": start_fg,
     "stop": stop, "status": status}.get(action, status)()
