import pytest_asyncio

from bot.db import Database
from bot.models import UserSettings


@pytest_asyncio.fixture
async def db():
    database = Database(":memory:")
    await database.connect()
    yield database
    await database.close()


@pytest_asyncio.fixture
async def user(db):
    u, _ = await db.get_or_create_user(1001, 1001, "Тест", default_settings=UserSettings(
        tz="Europe/Moscow", semester_start="2026-09-01"))
    return u
