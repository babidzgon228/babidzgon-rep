"""CallbackData-фабрики для инлайн-кнопок.

Правила:
- префиксы короткие (лимит callback_data — 64 байта);
- в значениях нельзя использовать ":" (разделитель aiogram), поэтому
  время кодируется как "0730", дата — как "20261106";
- длинные/юникодные значения (названия) в callback не кладём — только ключи и id.
"""
from __future__ import annotations

from datetime import date

from aiogram.filters.callback_data import CallbackData


# ---------------------------------------------------------------- кодирование значений

def d2s(d: date) -> str:
    """date -> "YYYYMMDD"."""
    return d.strftime("%Y%m%d")


def s2d(s: str) -> date:
    """"YYYYMMDD" (или ISO) -> date."""
    s = s.strip()
    if "-" in s:
        return date.fromisoformat(s)
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def t2s(hhmm: str) -> str:
    """"07:30" -> "0730"."""
    return hhmm.replace(":", "").replace(".", "")


def s2t(s: str) -> str:
    """"0730" -> "07:30"."""
    s = s.zfill(4)
    return f"{s[:2]}:{s[2:4]}"


# ---------------------------------------------------------------- фабрики

class NavCb(CallbackData, prefix="nav"):
    """Переход на экран: today / tomorrow / tasks / add / track / stats / week / settings / events / ai."""
    to: str


class StartCb(CallbackData, prefix="su"):
    """Быстрая настройка после /start: step = tz / wake / sleep / done / tzother."""
    step: str
    v: str = ""


class PlanCb(CallbackData, prefix="pl"):
    """Действия с планом дня: acc / re / ai / img / mk / ref / chk / show."""
    a: str
    d: str


class PlanItemCb(CallbackData, prefix="pi"):
    """Блок плана: start / done / skip / t (переключить «выполнено»)."""
    a: str
    d: str
    i: int


class TaskListCb(CallbackData, prefix="tl"):
    page: int = 0


class TaskCb(CallbackData, prefix="tk"):
    """Задача: view / done / undo / edit / tom / del / delok / why."""
    a: str
    id: int
    page: int = 0


class TaskFieldCb(CallbackData, prefix="tf"):
    """Переключатель поля задачи. id=0 — черновик в мастере добавления.

    f: imp / dl / est / en / cat / title / save / cancel / event / back
    """
    id: int
    f: str
    v: str = ""


class AddCb(CallbackData, prefix="ad"):
    """Что добавить: task / event / lesson."""
    kind: str


class EventCb(CallbackData, prefix="ev"):
    """Событие: list / view / del / delok / snooze / ok / add."""
    a: str
    id: int = 0


class EventWizCb(CallbackData, prefix="ew"):
    """Мастер события: f = date / time / rem / kind / cancel."""
    f: str
    v: str = ""


class TrackCb(CallbackData, prefix="tr"):
    """Трекер: menu / start / stop / past."""
    a: str
    cat: str = ""


class PastCb(CallbackData, prefix="tp"):
    """Записать прошедшее: cat -> ago (мин назад начал) -> dur (длительность, -2 = до сейчас)."""
    cat: str
    ago: int = -1
    dur: int = -1


class RateCb(CallbackData, prefix="rt"):
    """Оценка продуктивности активности (r=0 — пропустить)."""
    aid: int
    r: int


class CheckinCb(CallbackData, prefix="ci"):
    """Ответ на чек-ин: ключ категории или "same"."""
    cat: str


class StatsCb(CallbackData, prefix="st"):
    """Статистика: p = d / w / m, o — смещение назад (0 = текущий период)."""
    p: str = "d"
    o: int = 0


class TtCb(CallbackData, prefix="tt"):
    """Расписание: w (неделя) / add / del (выбор дня) / dday / dl / dlok / up / imp."""
    a: str
    o: int = 0
    day: int = -1
    id: int = 0


class LessonWizCb(CallbackData, prefix="lw"):
    """Мастер пары: f = day / time / subj / kind / room / par / cancel."""
    f: str
    v: str = ""


class SetCb(CallbackData, prefix="s"):
    """Настройки: f — поле (короткий ключ), v — значение ("" — открыть варианты)."""
    f: str
    v: str = ""


class DeadlineCb(CallbackData, prefix="dl"):
    """Напоминание о дедлайне: done / tom."""
    a: str
    id: int


class AiCb(CallbackData, prefix="ai"):
    """ИИ: clear / task / event / photo / on / nophoto."""
    a: str
