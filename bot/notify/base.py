"""Notifier interface (pluggable). Alerts are fire-and-forget; a slow or failing
notifier must never block trading."""
from __future__ import annotations

import abc


class Notifier(abc.ABC):
    @abc.abstractmethod
    def send(self, text: str) -> None: ...

    def info(self, text: str) -> None:
        self.send(f"ℹ️ {text}")

    def warn(self, text: str) -> None:
        self.send(f"⚠️ {text}")

    def trade(self, text: str) -> None:
        self.send(f"💹 {text}")

    def alert(self, text: str) -> None:
        self.send(f"🚨 {text}")

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None
