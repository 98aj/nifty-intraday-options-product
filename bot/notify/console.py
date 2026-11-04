"""Console notifier — fallback when no Telegram token is configured.

Encodes defensively: Windows consoles default to cp1252 and would raise on the
emoji used in alerts, so output is made safe for the active stdout encoding.
"""
from __future__ import annotations

import sys
from datetime import datetime

from bot.notify.base import Notifier


class ConsoleNotifier(Notifier):
    def send(self, text: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] [notify] {text}"
        enc = (getattr(sys.stdout, "encoding", None) or "utf-8")
        try:
            safe = line.encode(enc, errors="replace").decode(enc, errors="replace")
        except Exception:
            safe = line.encode("ascii", errors="replace").decode("ascii")
        print(safe, flush=True)
