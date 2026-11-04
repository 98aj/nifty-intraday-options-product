"""Pick a notifier: Telegram if a token is present, else console fallback."""
from __future__ import annotations

from bot.notify.base import Notifier
from bot.notify.console import ConsoleNotifier


def build_notifier(cfg, command_queue=None, state_provider=None) -> Notifier:
    backend = cfg.notify.backend
    token = cfg.secrets.telegram_bot_token
    chat = cfg.secrets.telegram_chat_id
    use_tg = (backend == "telegram") or (backend == "auto" and token and chat)
    if use_tg and token and chat:
        from bot.notify.telegram_bot import TelegramNotifier
        return TelegramNotifier(token, chat, command_queue, state_provider)
    return ConsoleNotifier()
