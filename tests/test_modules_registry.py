from bot.models import User, UserSettings
from bot.modules import registry
from bot.timeutil import now_utc


def _user(**prefs) -> User:
    return User(1, 1, "T", UserSettings(modules=prefs), now_utc())


def test_defaults_and_core():
    u = _user()
    keys = [m.key for m in registry.enabled_modules(u)]
    assert "today" in keys and "tasks" in keys and "study" in keys
    assert "cycle" not in keys and "friends" not in keys
    u2 = _user(today=False, study=False, cycle=True)
    assert registry.enabled(u2, "today")          # core нельзя выключить
    assert not registry.enabled(u2, "study") and registry.enabled(u2, "cycle")


def test_menu_layout():
    rows = registry.menu_layout(_user())
    flat = [m.key for r in rows for m in r]
    assert flat[:3] == ["today", "tasks", "add"] and flat[-1] == "more"
    assert all(len(r) <= 3 for r in rows) and "cycle" not in flat
    assert flat == ["today", "tasks", "add", "study", "focus", "progress", "more"]   # только готовые разделы
    flat2 = [m.key for r in registry.menu_layout(_user(study=False)) for m in r]
    assert "study" not in flat2 and len(flat2) == len(flat) - 1


async def test_set_enabled(db, user):
    await registry.set_enabled(db, user, "money", False)
    assert (await db.get_user(user.id)).settings.modules == {"money": False}
    await registry.set_enabled(db, user, "today", False)   # core игнорируется
    assert registry.enabled(await db.get_user(user.id), "today")
