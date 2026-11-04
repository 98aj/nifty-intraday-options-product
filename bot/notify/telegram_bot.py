"""Telegram notifier + inbound command handler.

Outbound alerts and inbound commands run on a single background thread using the
Telegram Bot HTTP API (long-poll getUpdates). Commands are accepted ONLY from the
configured chat id and are pushed onto the shared CommandQueue — the handler never
executes engine logic itself. Sending is fire-and-forget so Telegram latency can
never stall trading.

(We use the Bot HTTP API directly via httpx for a small, robust, thread-friendly
footprint; python-telegram-bot is listed as a dependency for teams who prefer it.)
"""
from __future__ import annotations

import queue
import threading
from typing import Optional

import httpx

from bot.core.commands import CommandQueue, CommandType, VALID_COMMANDS
from bot.notify.base import Notifier

API = "https://api.telegram.org"


class TelegramNotifier(Notifier):
    def __init__(self, token: str, chat_id: str,
                 command_queue: Optional[CommandQueue] = None,
                 state_provider=None) -> None:
        self.token = token
        self.chat_id = str(chat_id)
        self.command_queue = command_queue
        self.state_provider = state_provider      # callable -> status text
        self._out: "queue.Queue[str]" = queue.Queue(maxsize=1000)
        self._stop = threading.Event()
        self._send_thread: Optional[threading.Thread] = None
        self._poll_thread: Optional[threading.Thread] = None
        self._offset = 0
        self._client = httpx.Client(timeout=35.0)

    def _url(self, method: str) -> str:
        return f"{API}/bot{self.token}/{method}"

    # ---- Notifier API ----
    def send(self, text: str) -> None:
        try:
            self._out.put_nowait(text)
        except queue.Full:
            pass

    def start(self) -> None:
        self._send_thread = threading.Thread(target=self._send_loop,
                                              name="TgSend", daemon=True)
        self._send_thread.start()
        if self.command_queue is not None:
            self._poll_thread = threading.Thread(target=self._poll_loop,
                                                  name="TgPoll", daemon=True)
            self._poll_thread.start()
        self.info("NIFTY bot notifier online.")

    def stop(self) -> None:
        self._stop.set()
        try:
            self._client.close()
        except Exception:
            pass

    # ---- outbound ----
    def _send_loop(self) -> None:
        while not self._stop.is_set():
            try:
                text = self._out.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._client.post(self._url("sendMessage"),
                                  json={"chat_id": self.chat_id, "text": text})
            except Exception:
                pass

    # ---- inbound commands (only from configured chat) ----
    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            try:
                r = self._client.get(self._url("getUpdates"),
                                     params={"offset": self._offset + 1,
                                             "timeout": 30})
                data = r.json()
            except Exception:
                continue
            for upd in data.get("result", []):
                self._offset = max(self._offset, upd.get("update_id", 0))
                msg = upd.get("message") or upd.get("channel_post") or {}
                chat = str((msg.get("chat") or {}).get("id", ""))
                text = (msg.get("text") or "").strip().lstrip("/").lower()
                if chat != self.chat_id:
                    continue                       # ignore everyone else
                if text in VALID_COMMANDS:
                    self._dispatch(text)
                else:
                    self.info(f"unknown command '{text}'. Valid: "
                              f"{', '.join(sorted(VALID_COMMANDS))}")

    def _dispatch(self, text: str) -> None:
        if text == CommandType.STATUS.value and self.state_provider:
            self.info(self.state_provider())
            return
        self.command_queue.submit(CommandType(text), source="telegram")
        self.trade(f"command '{text}' received.")
