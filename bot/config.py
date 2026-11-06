"""Настройки из переменных окружения (.env)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv


@dataclass
class Config:
    bot_token: str
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-5-5"
    allowed_user_ids: set[int] = field(default_factory=set)
    default_tz: str = "Europe/Moscow"
    db_path: str = "data/bot.db"
    timetable_path: str = "data/timetable.yaml"
    telegram_proxy: str | None = None   # http://… или socks5://… (если Telegram заблокирован)

    @property
    def ai_available(self) -> bool:
        return bool(self.anthropic_api_key)


def load_config() -> Config:
    load_dotenv()
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("BOT_TOKEN не задан. Скопируй .env.example в .env и впиши токен от @BotFather.")
    allowed = {int(x) for x in os.getenv("ALLOWED_USER_IDS", "").replace(" ", "").split(",") if x}
    return Config(
        bot_token=token,
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", "").strip() or None,
        anthropic_model=os.getenv("ANTHROPIC_MODEL", "").strip() or "claude-opus-5-5",
        allowed_user_ids=allowed,
        default_tz=os.getenv("DEFAULT_TZ", "Europe/Moscow").strip(),
        db_path=os.getenv("DB_PATH", "data/bot.db").strip(),
        timetable_path=os.getenv("TIMETABLE_PATH", "data/timetable.yaml").strip(),
        telegram_proxy=os.getenv("TELEGRAM_PROXY", "").strip() or None,
    )
