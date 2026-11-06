"""Распознавание голосовых сообщений (локально, бесплатно) через faster-whisper.

Опционально: `pip install -r requirements-voice.txt`. Без пакета available() == False,
а бот вежливо говорит, что голосовые не включены.
Модель задаётся env WHISPER_MODEL (tiny / base / small; по умолчанию base — ~150 МБ, ~1 ГБ RAM).
Распознавание идёт в отдельном потоке, чтобы не блокировать бота.
"""
from __future__ import annotations

import asyncio
import io
import logging
import os
import threading
from typing import Any

log = logging.getLogger(__name__)

_model: Any = None
_model_lock = threading.Lock()
_sem = asyncio.Semaphore(1)  # одно распознавание за раз — бережём слабый сервер


def available() -> bool:
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return os.getenv("VOICE_ENABLED", "1") not in ("0", "false", "no")


def _get_model() -> Any:
    global _model
    with _model_lock:
        if _model is None:
            from faster_whisper import WhisperModel
            name = os.getenv("WHISPER_MODEL", "base")
            log.info("voice: загружаю модель Whisper %s…", name)
            _model = WhisperModel(name, device="cpu", compute_type="int8")
        return _model


def _transcribe_sync(data: bytes, lang: str | None) -> str:
    model = _get_model()
    # ru / en / zh — подсказка языка ускоряет и улучшает распознавание; None — автоопределение
    segments, _info = model.transcribe(io.BytesIO(data), language=lang, vad_filter=True, beam_size=1)
    return " ".join(s.text.strip() for s in segments).strip()


async def transcribe(data: bytes, lang: str | None = None) -> str | None:
    """Текст голосового (OGG/Opus из Telegram). None — если недоступно или не вышло."""
    if not available():
        return None
    async with _sem:
        try:
            text = await asyncio.to_thread(_transcribe_sync, data, lang)
        except Exception:  # noqa: BLE001 — бот не должен падать из-за распознавания
            log.exception("voice: ошибка распознавания")
            return None
    return text or None
