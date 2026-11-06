from bot.i18n import CATALOGS, L, all_langs, t, tp
from bot.models import UserSettings


def test_t_fallback_and_format():
    assert t("common.back", "en") == "◀️ Back"
    assert t("common.back", "xx") == "◀️ Назад"           # неизвестный язык -> ru
    assert t("no.such.key", "zh") == "no.such.key"
    assert L(UserSettings(lang="zh")) == "zh" and L(UserSettings()) == "ru"


def test_plurals():
    assert [tp("unit.lesson", n, "ru") for n in (1, 2, 5, 11, 21, 22)] == \
        ["1 пара", "2 пары", "5 пар", "11 пар", "21 пара", "22 пары"]
    assert tp("unit.lesson", 1, "en") == "1 class" and tp("unit.lesson", 3, "en") == "3 classes"
    assert tp("unit.lesson", 3, "zh") == "3节课"


def test_all_langs_and_catalog_parity():
    assert all_langs("common.back") == {"◀️ Назад", "◀️ Back", "◀️ 返回"}
    ru_keys = set(CATALOGS["ru"])
    for lang in ("en", "zh"):
        missing = ru_keys - set(CATALOGS[lang])
        assert not missing, f"{lang}: нет переводов для {sorted(missing)[:20]}"
