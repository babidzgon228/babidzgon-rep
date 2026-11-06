# Архитектура и контракты модулей

Личный Telegram-бот-планировщик для студента. Язык интерфейса — **русский**.
Python 3.11+, aiogram 3.x, SQLite (aiosqlite), Claude API (anthropic SDK 2.x).
Запуск: `python -m bot`. Тесты: `pytest`.

## Что умеет бот (продуктовые требования)

1. **Трекер «что я делаю»**: таймер по категориям (`ACTIVITY_CATEGORIES`), стоп с оценкой продуктивности 1–5,
   ручное добавление прошедшей активности, периодические чек-ины «Что делаешь сейчас?» с кнопками категорий.
2. **Задачи с оценкой эффективности**: важность 1–3, дедлайн, оценка времени, сложность (энергия), категория.
   Приоритет считается автоматически (score 0..100 + квадрант Эйзенхауэра), список задач — отсортирован.
3. **План на завтра**: автоматически каждый вечер (`evening_plan_time`): пары + события — фиксированные блоки,
   задачи раскладываются по свободным окнам по приоритету с учётом энергии (сложное — в пик продуктивности),
   перерывы, еда. Кнопки: принять / перестроить / улучшить с ИИ / картинкой.
4. **Напоминания**: о парах (за `class_reminder_min`), событиях (за `remind_before_min`), блоках принятого плана,
   дедлайнах (за 24 ч и за 2 ч), утренняя сводка, вечерний отчёт.
5. **ИИ (Claude)**: свободный текст → ассистент с инструментами (создаёт задачи/события, запускает трекер,
   отвечает про расписание и статистику), улучшение плана, инсайт по итогам дня, распознавание расписания
   по фото/тексту.
6. **Учебное расписание**: недельное, с чётностью недель (числитель/знаменатель), импорт из `data/timetable.yaml`
   при первом /start, редактирование в боте, загрузка фото расписания → ИИ распознаёт.
7. **Удобный интерфейс**: постоянное меню (reply-клавиатура), инлайн-кнопки везде, минимум ручного ввода,
   редактирование сообщений вместо спама новыми.

## Владение файлами (кто что пишет)

| Модуль | Владелец |
|---|---|
| `bot/models.py`, `bot/db.py`, `bot/timeutil.py`, `bot/config.py`, `bot/middlewares.py`, `bot/__main__.py`, `bot/services/timetable.py` | **Фундамент (готово, не менять без согласования; можно ДОБАВЛЯТЬ методы в db.py, если очень нужно — опиши в отчёте)** |
| `bot/ui/*`, `bot/handlers/*` | Агент «Интерфейс и дизайн» |
| `bot/ai/*` | Агент «ИИ» |
| `bot/services/prioritizer.py`, `planner.py`, `stats.py`, `notifier.py` | Агент «Планировщик» |
| `tests/test_<твой_модуль>*.py` | каждый агент — свои тесты |

Каждый stub-файл содержит **обязательные сигнатуры**. Их нельзя менять (другие модули их вызывают).
Можно добавлять свои функции/классы.

## Общие правила

- Все datetime — **aware**. В БД — UTC. Пользователю показываем в `user.settings.tz` (`bot.timeutil.to_local`).
- Время внутри дня — строки `"HH:MM"` в локальном поясе (PlanItem, Lesson).
- Сообщения — **Telegram HTML** (`parse_mode=HTML` стоит по умолчанию у Bot). Любой пользовательский текст
  экранировать `html.escape`. Разрешённые теги: `<b> <i> <u> <s> <code> <pre> <a> <blockquote> <tg-spoiler>`.
- Никаких блокирующих вызовов в event loop (Pillow-рендер можно в `asyncio.to_thread`).
- Хендлеры получают через DI aiogram (workflow_data + middleware) аргументы:
  `db: Database`, `ai: AIAssistant`, `config: Config`, `notifier: Notifier | None`, `user: User`, `user_created: bool`, `bot: Bot`, `state: FSMContext`.

## Контракты

### Фундамент (готово)
- `bot.db.Database` — см. файл: users/settings, tasks, events, lessons, activities (трекер), plans,
  `was_sent/mark_sent` (дедупликация уведомлений), `add_ai_message/get_ai_history`, `get_state/set_state`.
- `bot.services.timetable`: `week_parity(d, settings)`, `week_number(d, settings)`,
  `lessons_for_date(db, user, d)`, `normalize_lesson_dict(raw)`, `import_lessons(db, user_id, lessons, replace)`,
  `load_timetable_file(path)`, `seed_from_file_if_empty(db, user, path)`.
- `bot.timeutil`: `now_utc, to_local, local_now, local_today, combine_local, minutes_of, hhmm_of,
  day_bounds_utc, human_duration, parse_hhmm, fmt_hhmm`.

### Планировщик — `bot/services/`
- `prioritizer`: `QUADRANT_LABELS`, `urgency(task, now)`, `score_task(task, now) -> 0..100`,
  `quadrant(task, now) -> "do"|"plan"|"quick"|"later"`, `prioritize(tasks, now)`, `explain_score(task, now)`.
- `planner`: `build_plan_items(d, settings, lessons, events, tasks, now) -> list[PlanItem]` (чистая),
  `build_plan(db, user, d, save=True) -> DayPlan`.
- `stats`: `day_stats(db, user, d) -> DayStats`, `period_stats(db, user, start, end) -> PeriodStats`.
- `notifier.Notifier(bot, db, ai=None, interval_sec=30)`: `run()`, `stop()`, `tick(now=None)`,
  `send_morning(user)`, `send_evening(user)`. Использует `bot.ui.texts` и `bot.ui.keyboards` (функции ниже).

### Интерфейс — `bot/ui/`, `bot/handlers/`
- `ui.texts` (обязательные): `day_plan(plan, header=None, now_local=None)`, `morning_brief(user, d, lessons, events, top_tasks, plan)`,
  `lesson_reminder(lesson, minutes_left)`, `event_reminder(event, minutes_left, tz_name)`, `plan_item_reminder(item)`,
  `deadline_reminder(task, tz_name, hours_left)`, `checkin_prompt(current, tz_name)`, `day_report(stats, ai_comment=None)`.
- `ui.keyboards` (обязательные): `main_menu()`, `plan_actions(d, status)`, `checkin_keyboard()`,
  `plan_item_actions(d, index, item)`, `event_reminder_actions(event_id)`, `deadline_actions(task_id)`,
  `rating_keyboard(activity_id)`. Callback-данные этих кнопок обрабатывают хендлеры (тот же агент).
- `ui.cards.render_day_card(plan, title=..., subtitle=None) -> bytes` (PNG).
- `handlers`: `BOT_COMMANDS: list[BotCommand]`, `setup_routers() -> Router`.

### ИИ — `bot/ai/`
- `AIReply(text, actions, changed)`.
- `AIAssistant(db, api_key, model)`: `enabled`, `chat(user, text) -> AIReply`,
  `improve_plan(user, plan, lessons=, events=, tasks=) -> DayPlan`,
  `day_insight(user, stats, plan, activities) -> str | None`,
  `parse_timetable(text=None, image=None, mime=...) -> list[dict]` (словари для `normalize_lesson_dict`),
  `suggest_task_fields(user, title) -> dict` (`importance, estimate_min, energy, category, deadline?`).
- Все методы при `enabled == False` или ошибке API не падают: `chat` возвращает понятный текст,
  `improve_plan` возвращает исходный план, остальные — `None`/`[]`/`{}`.
