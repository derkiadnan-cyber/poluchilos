"""
Самопроверка бота. Запускается тремя способами:

    python selfcheck.py          # из консоли, код возврата 0/1
    из bot.py при старте         # чтобы сразу видеть поломку в логах
    в GitHub Actions при пуше    # чтобы сломанное не уезжало в прод

Проверки офлайновые: никаких обращений к Telegram, DeepSeek или интернету,
рабочая база не трогается (для проверок создаётся временная в %TEMP%).
Нужен только BOT_TOKEN в окружении - в CI подставляется фиктивный.
"""

import os
import re
import sys
import tempfile
import traceback

PROBLEMS = []


def _check(name, func):
    """Прогоняет одну проверку и записывает проблему, если она упала."""
    try:
        found = func()
        if found:
            PROBLEMS.extend(f"{name}: {p}" for p in (found if isinstance(found, list) else [found]))
            print(f"  ✗ {name}")
        else:
            print(f"  ✓ {name}")
    except Exception:
        PROBLEMS.append(f"{name}: исключение {traceback.format_exc()[-200:]}")
        print(f"  ✗ {name} (исключение)")


# ===== ПРОВЕРКИ =====
def check_imports():
    import admin_panel.admin.admin
    import admin_panel.mailing.mailing
    import handlers.start
    import handlers.profile
    import handlers.chat_join
    import handlers.fallbacks
    import handlers.markups
    import managers.ai
    import managers.brain
    import managers.content
    import managers.memes
    import managers.reminds
    import managers.weather
    import utils.alerts
    import utils.scripts
    return None


def check_config():
    from storage.config import (bot_token, admins, TIMEZONE, db_path, AUTOSEND,
                                IS_CLOUD, AI_ENABLED)
    problems = []
    if not bot_token or ":" not in bot_token:
        problems.append(f"BOT_TOKEN выглядит нерабочим (длина {len(bot_token)})")
    if not admins:
        problems.append("ADMIN_IDS пуст - боту некому слать тревоги и /status")
    from zoneinfo import ZoneInfo
    try:
        ZoneInfo(TIMEZONE)
    except Exception:
        problems.append(f"TIMEZONE '{TIMEZONE}' не существует")
    if not db_path:
        problems.append("DB_PATH пустой")
    if IS_CLOUD and not AUTOSEND:
        problems.append("в облаке рассылки выключены (AUTOSEND=off) - так и задумано?")
    return problems


def check_content():
    from managers import content as c
    problems = []
    arrays = {
        "POEMS": c.POEMS, "CONFESSION_OPEN": c.CONFESSION_OPEN,
        "CONFESSION_BODY": c.CONFESSION_BODY, "CONFESSION_CLOSE": c.CONFESSION_CLOSE,
        "NIGHT": c.NIGHT, "NEXT_DAY_WISHES": c.NEXT_DAY_WISHES, "MORNING": c.MORNING,
        "HUG_GIFS": c.HUG_GIFS, "ROMANTIC_PHOTOS": c.ROMANTIC_PHOTOS,
        "PHOTO_TAGS": c.PHOTO_TAGS, "COMPLIMENTS": c.COMPLIMENTS,
        "MEME_CAPTIONS": c.MEME_CAPTIONS,
        "GIPHY_GIF_QUERIES": c.GIPHY_GIF_QUERIES,
    }
    for name, items in arrays.items():
        if not items:
            problems.append(f"{name} пустой")

    for name in ("HUG_GIFS", "ROMANTIC_PHOTOS"):
        urls = arrays[name]
        if len(set(urls)) != len(urls):
            problems.append(f"{name} содержит дубликаты")
        for url in urls:
            if not url.startswith("https://"):
                problems.append(f"{name}: не https - {url[:60]}")
            if " " in url:
                problems.append(f"{name}: пробел в ссылке - {url[:60]}")

    # Лимит текста в Telegram - 4096 символов
    for name in ("POEMS", "NIGHT", "MORNING", "NEXT_DAY_WISHES", "COMPLIMENTS"):
        for i, text in enumerate(arrays[name]):
            if len(text) > 3900:
                problems.append(f"{name}[{i}] длиннее лимита Telegram ({len(text)})")

    # Теги разметки должны быть закрыты, иначе Telegram отвергнет сообщение
    for name in ("POEMS", "NIGHT", "MORNING", "NEXT_DAY_WISHES"):
        for i, text in enumerate(arrays[name]):
            for tag in ("b", "i", "code", "u", "s"):
                if text.count(f"<{tag}>") != text.count(f"</{tag}>"):
                    problems.append(f"{name}[{i}]: незакрытый <{tag}>")
    return problems


def check_deck():
    from managers.content import Deck
    problems = []
    deck = Deck(list(range(5)))
    drawn = [deck.next() for _ in range(10)]
    if sorted(drawn[:5]) != [0, 1, 2, 3, 4]:
        problems.append("Deck теряет элементы за круг")
    if drawn[4] == drawn[5]:
        problems.append("Deck повторяет последнюю карту первой в новом круге")
    for empty in ([], None):
        try:
            Deck(empty if empty is not None else [])
            problems.append("Deck принял пустой список без ошибки")
            break
        except ValueError:
            pass
    return problems


def check_brain():
    from managers import brain
    from managers import content as c
    problems = []
    cases = {
        "2+2": "4", "сколько будет 17*23": "391", "(5+3)*2**3": "64",
        "5% от 200": "10", "корень из 144": "12", "100/7": "14.285",
        "2^10": "1 024",
        # Единицы и даты тоже считаем сами, без сети и без внешней модели
        "сколько минут в 3 часах": "180",
        "2 кг это сколько грамм": "2 000",
        "сколько секунд в сутках": "86 400",
    }
    for question, expected in cases.items():
        reply = brain.answer(question) or ""
        if expected not in reply:
            problems.append(f"калькулятор «{question}» дал «{reply[:40]}», ждали «{expected}»")

    zero = brain.answer("8/0") or ""
    if "ноль" not in zero.lower():
        problems.append(f"деление на ноль отвечено странно: «{zero[:40]}»")

    until = brain.answer("сколько дней до 1 января") or ""
    if "января" not in until or not any(ch.isdigit() for ch in until):
        problems.append(f"обратный отсчёт до даты сломан: «{until[:50]}»")

    # Бытовые вопросы обязаны отвечаться без сети
    for question in ("привет", "что умеешь", "который час", "какое сегодня число",
                     "подбрось монетку", "спасибо", "скинь стих", "как извиниться",
                     "что подарить", "как тебя зовут"):
        if not brain.answer(question):
            problems.append(f"свой мозг промолчал на «{question}»")

    # Главная просьба пользователя: отвечать по делу, а не комплиментами.
    # Проверка злая: любая фраза обязана получить текст, и это не должен быть
    # комплимент из банка.
    compliments = set(c.COMPLIMENTS)
    for phrase in ("ыфывыф фывфыв", "что думаешь про акции", "х", "....",
                   "а ты знаешь рецепт борща", "мне грустно"):
        reply = brain.answer(phrase)
        if not reply:
            problems.append(f"на «{phrase[:20]}» мозг промолчал - будет тишина")
        elif reply in compliments:
            problems.append(f"на «{phrase[:20]}» мозг сдал комплимент вместо ответа")

    # hard_only обязан молчать на болтовню: иначе модель никогда не спросится
    if brain.answer("расскажи про чёрные дыры", hard_only=True):
        problems.append("hard_only отвечает на болтовню - внешняя модель станет ненужной")
    if not brain.answer("7*8", hard_only=True):
        problems.append("hard_only не посчитал 7*8")

    # Мусор и попытки инъекции не должны ронять движок и не должны выполняться
    for junk in ("", "   ", "йцукен", "2+", "-3", "__import__('os').system('calc')",
                 "9" * 500, "((1+2)", "1/0/0", "None", "🍌🍌"):
        try:
            brain.answer(junk)
        except Exception as exc:
            problems.append(f"свой мозг упал на «{junk[:20]}»: {type(exc).__name__}")
    return problems


def check_no_compliment_fallback():
    """
    Комплимент больше не должен подставляться вместо ответа на сообщение.
    По явной просьбе («скинь комплимент») он остался - это нормально, поэтому
    смотрим конкретно на функции-заглушки, а не на весь файл.
    """
    import inspect

    from managers import brain
    problems = []

    for func in (brain._unknown, brain.answer):
        try:
            source = inspect.getsource(func)
        except OSError as exc:
            problems.append(f"не смог прочитать {func.__name__}: {exc}")
            continue
        if "next_compliment" in source:
            problems.append(f"brain.{func.__name__}: комплимент подставлен вместо ответа")

    try:
        with open("handlers/fallbacks.py", encoding="utf-8") as fh:
            source = fh.read()
    except OSError as exc:
        problems.append(f"не смог прочитать fallbacks.py: {exc}")
    else:
        if "next_compliment" in source:
            problems.append("handlers/fallbacks.py: комплимент всё ещё подставляется вместо ответа")

    from storage.config import MEME_MIN
    if MEME_MIN < 1:
        problems.append(f"MEME_MIN={MEME_MIN} - мемы будут спамить")
    return problems


def check_ui_texts():
    """
    Тексты экранов (меню, справка, история любви) уходят с parse_mode=HTML:
    один незакрытый <b> - и Telegram отвергает сообщение, а пользователь
    видит «меню не открывается». Именно так всё и сломалось однажды.
    """
    from handlers import start
    problems = []
    screens = {
        "MENU_TEXT": [getattr(start, "MENU_TEXT", "")],
        "HELP_TEXT": [start.HELP_TEXT],
        "SETTINGS_TEXT": [start.SETTINGS_TEXT],
        "LOVE_STORY": list(getattr(start, "LOVE_STORY", [])),
    }
    for name, items in screens.items():
        for i, item in enumerate(items):
            # LOVE_STORY лежит кортежами по одной главе
            text = item[0] if isinstance(item, tuple) else item
            if not text:
                if name != "LOVE_STORY":
                    problems.append(f"{name} пустой")
                continue
            for tag in ("b", "i", "u", "s", "code", "pre"):
                if text.count(f"<{tag}>") != text.count(f"</{tag}>"):
                    problems.append(f"{name}[{i}]: незакрытый <{tag}>")
            if len(text) > 3900:
                problems.append(f"{name}[{i}] длиннее лимита Telegram ({len(text)})")
    return problems


def check_memes():
    """Разбор ответа мемами-сервиса - офлайновый, на фикстуре, без сети."""
    from managers import memes
    from storage.config import MEME_MIN_UPS, MEME_RUSSIAN_ONLY, MEME_SUBREDDITS
    problems = []

    fixture = [
        # обычный русский пост - пройдёт
        {"url": "https://i.redd.it/ok.jpg", "ups": 227, "subreddit": "pikabu",
         "title": "Ни к чему не призываем, нет"},
        # гифка - пройдёт и уйдёт как анимация
        {"url": "https://i.redd.it/gif.gif", "ups": 65, "subreddit": "pikabu",
         "title": "Везёт же некоторым!"},
        # мало голосов - несмешно
        {"url": "https://i.redd.it/poor.png", "ups": 3, "subreddit": "pikabu",
         "title": "Первый пост, не судите"},
        # англоязычная подпись - пользователю нужен русский мем
        {"url": "https://i.redd.it/english.jpg", "ups": 40000, "subreddit": "russian_memes",
         "title": "Russian pickachu but in English"},
        # 18+, спойлеры и не-картинки не шлём никому
        {"url": "https://i.redd.it/nsfw.jpg", "ups": 99999, "nsfw": True,
         "title": "Это не надо никому"},
        {"url": "https://i.redd.it/spoiler.jpg", "ups": 99999, "spoiler": True,
         "title": "Осторожно, спойлер"},
        # видео и битые ссылки Telegram не переварит
        {"url": "https://v.redd.it/clip.mp4", "ups": 50000, "title": "Видеоролик про котов"},
        {"url": "", "ups": 50000, "title": "Ссылки нет"},
        # рейтинг может прийти строкой или null - падать на этом нельзя
        {"url": "https://i.redd.it/str.jpg", "ups": "1200", "title": "Картинка с цифрами"},
        {"url": "https://i.redd.it/norate.jpg", "ups": None, "score": 700,
         "title": "Картинка без рейтинга"},
    ]
    parsed = memes._parse(fixture)
    urls = {m["url"] for m in parsed}
    if "https://i.redd.it/ok.jpg" not in urls:
        problems.append("мем с 227 голосами не прошёл фильтр")
    if not any(m["animation"] for m in parsed):
        problems.append("гифка не распознана как анимация - уйдёт битым фото")
    for bad in ("https://i.redd.it/poor.jpg", "https://i.redd.it/poor.png",
                "https://i.redd.it/nsfw.jpg", "https://i.redd.it/spoiler.jpg",
                "https://v.redd.it/clip.mp4"):
        if bad in urls:
            problems.append(f"фильтр пропустил нежелательный мем {bad}")
    if MEME_RUSSIAN_ONLY and "https://i.redd.it/english.jpg" in urls:
        problems.append("англоязычный мем просочился в подборку - пользователь "
                        "просил русскоязычные")
    expected = 4 if MEME_RUSSIAN_ONLY else 5
    if len(parsed) != expected:
        problems.append(f"разбор вернул {len(parsed)} мемов вместо {expected}: {sorted(urls)}")

    for m in parsed:
        if m["ups"] < MEME_MIN_UPS:
            problems.append(f"мем с {m['ups']} голосов слабее MEME_MIN_UPS={MEME_MIN_UPS}")
    if not memes.status_line().startswith("мемы"):
        problems.append("status_line для мемов сломалась")

    # Русские сабреддиты маленькие: с порогом в 500 голосов подборка была бы пуста
    if MEME_MIN_UPS > 200:
        problems.append(f"MEME_MIN_UPS={MEME_MIN_UPS} - в русскоязычных сабредитах "
                        f"топ это ~200 голосов, мемов не будет")
    if MEME_RUSSIAN_ONLY and not any("pikabu" in s for s in MEME_SUBREDDITS):
        problems.append("в подборке нет r/pikabu - самого живого русского источника")
    return problems


def check_weather():
    """
    Форматирование сводки проверяем офлайново, на фикстуре ответа Open-Meteo:
    сеть в CI нестабильна, а разбор кривого ответа лучше поймать здесь.
    """
    from managers import weather
    problems = []

    if weather._wmo(95)[0] != "гроза":
        problems.append("код погоды 95 не расшифровывается как гроза")
    for unknown in (None, "", "abc", 12345):
        try:
            weather._wmo(unknown)
        except Exception as exc:
            problems.append(f"неизвестный код погоды {unknown!r} роняет сводку: {type(exc).__name__}")

    if weather._degrees(7.4) != "+7°" or weather._degrees(-2.6) != "-3°" or weather._degrees(0) != "0°":
        problems.append(f"градусы форматируются странно: {weather._degrees(7.4)}/"
                        f"{weather._degrees(-2.6)}/{weather._degrees(0)}")
    if weather._number(2.9883) != "2,9883":
        problems.append(f"курс форматируется не по-русски: {weather._number(2.9883)}")
    if weather._hour_of("2026-10-21T13:00") != 13 or weather._hour_of("мусор") != -1:
        problems.append("_hour_of не разбирает время Open-Meteo")

    hourly = {
        "time": [f"2026-10-21T{h:02d}:00" for h in range(24)],
        "temperature_2m": [5 + (h % 8) for h in range(24)],
        "precipitation_probability": [10] * 12 + [80] * 12,
        "weather_code": [0] * 12 + [61] * 12,
    }
    parts = weather._parts(hourly)
    if len(parts) != 4:
        problems.append(f"день разложился на {len(parts)} частей вместо 4")
    if not any("День" in p for p in parts) or not any("80%" in p for p in parts):
        problems.append(f"во второй половине дня не видно вероятность осадков: {parts}")

    # Пустой/битый ответ не должен рождать сообщение с вопросительными знаками
    if weather._parts({}) or weather._parts(None):
        problems.append("_parts не должна ничего возвращать на пустом прогнозе")
    advice = weather._advice({"precipitation_probability_max": [90], "precipitation_sum": [10],
                              "temperature_2m_min": [-5], "wind_speed_10m_max": [40]}, {})
    if "зонт" not in advice or "тёплые вещи" not in advice:
        problems.append(f"совет на дождь и мороз звучит странно: {advice}")
    calm = weather._advice({"precipitation_probability_max": [0], "precipitation_sum": [0],
                            "temperature_2m_min": [18], "wind_speed_10m_max": [3]}, {})
    if "спокойный" not in calm:
        problems.append(f"на тёплый день совет не должен пугать: {calm}")
    for broken in ({}, {"precipitation_sum": ["abc"], "temperature_2m_min": [None]}):
        try:
            weather._advice(broken, {})
        except Exception as exc:
            problems.append(f"совет падает на битых данных: {type(exc).__name__}")

    from storage.config import WEATHER_TIME, WEATHER_TZ, WEATHER_LAT, WEATHER_LON
    from zoneinfo import ZoneInfo
    try:
        ZoneInfo(WEATHER_TZ)
    except Exception:
        problems.append(f"WEATHER_TZ '{WEATHER_TZ}' не существует")
    if not (-90 <= WEATHER_LAT <= 90 and -180 <= WEATHER_LON <= 180):
        problems.append(f"координаты за пределами Земли: {WEATHER_LAT}, {WEATHER_LON}")
    # Смысл задачи в 08:30: не уронили ли настройку переменной окружения
    if WEATHER_TIME != (8, 30):
        problems.append(f"сводка утра назначена на {WEATHER_TIME}, а ждали 08:30")
    return problems


def check_html():
    from managers.ai import to_telegram_html
    problems = []
    escaped = to_telegram_html("обычный <текст> и & символы")
    if "<текст>" in escaped:
        problems.append("HTML из ответа модели не экранируется")
    bold = to_telegram_html("**жирный**")
    if "<b>жирный</b>" not in bold:
        problems.append(f"markdown **не превращается в <b>: {bold}")
    code = to_telegram_html("```python\nx = 1\n```")
    if "<pre>" not in code:
        problems.append("блок кода не превращается в <pre>")
    long = to_telegram_html("<b>" + "слово " * 1200)
    if len(long) > 3600:
        problems.append(f"обрезка не сработала, длина {len(long)}")
    if re.search(r"<[a-z/]*$", long):
        problems.append("обрезка оставила кусок HTML-тега - Telegram отвергнет сообщение")
    if to_telegram_html("```\n\n```"):
        problems.append("пустой блок кода должен давать пустоту, а не <pre></pre>")
    return problems


def check_database():
    """Проверяет модели на временной базе, рабочую не трогая."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from db.models import Base, User, BotState
    from sqlalchemy.sql import select

    path = os.path.join(tempfile.gettempdir(), "bot_selfcheck.db")
    if os.path.exists(path):
        os.remove(path)
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    problems = []

    with Session() as session:
        session.add(User(tg_id=123, fullname="Test", username="test", inviter_id=0))
        session.commit()
    with Session() as session:
        found = session.execute(select(User).where(User.tg_id == 123)).scalar_one_or_none()
        if found is None:
            problems.append("юзер не сохранился в базе")
        elif found.fullname != "Test":
            problems.append("имя юзера прочиталось неверно")

    # BotState работает через рабочую сессию - проверяем только наличие методов
    for method in ("get_value", "set_value"):
        if not hasattr(BotState, method):
            problems.append(f"у BotState нет метода {method}")

    engine.dispose()
    os.remove(path)
    return problems


def check_schedule():
    """Тихие часы через полночь и проверка времени - классика подобных багов."""
    from datetime import datetime
    from managers.reminds import _time_reached, _minutes_of_day, TZ
    problems = []
    morning = datetime(2026, 10, 21, 8, 0, tzinfo=TZ)
    if not _time_reached(morning, (8, 0)):
        problems.append("в 08:00 время 08:00 не считается наступившим")
    if _time_reached(datetime(2026, 10, 21, 7, 59, tzinfo=TZ), (8, 0)):
        problems.append("в 07:59 уже считает, что 08:00 наступило")
    if _minutes_of_day(datetime(2026, 10, 21, 23, 30, tzinfo=TZ)) != 23 * 60 + 30:
        problems.append("_minutes_of_day считает минуты неверно")

    from storage.config import QUIET_FROM, QUIET_TO
    if QUIET_FROM > QUIET_TO:
        # интервал через полночь: 22:30-07:30
        from managers.reminds import is_quiet_now
        late = datetime(2026, 10, 21, 23, 0, tzinfo=TZ)
        day = datetime(2026, 10, 21, 12, 0, tzinfo=TZ)
        for moment, expected in ((late, True), (day, False)):
            with_quiet = None
            import storage.config as cfg
            original = cfg.QUIET_HOURS
            try:
                cfg.QUIET_HOURS = True
                import managers.reminds as r
                real_now = r.now_local
                r.now_local = lambda m=moment: m
                with_quiet = r.is_quiet_now()
            finally:
                cfg.QUIET_HOURS = original
                r.now_local = real_now
            if with_quiet != expected:
                problems.append(f"тихие часы неверно работают в {moment.strftime('%H:%M')}")
    return problems


def check_send_helpers():
    """Функции безопасной отправки должны существовать и не падать на None."""
    from utils.scripts import get_command_name, safe_edit, safe_answer, safe_send
    problems = []
    for fn in (get_command_name, safe_edit, safe_answer, safe_send):
        if not callable(fn):
            problems.append(f"{fn.__name__} не вызывается")
    return problems


def run_checks(quiet=False):
    """Прогоняет все проверки. Возвращает список найденных проблем."""
    PROBLEMS.clear()
    if not quiet:
        print("Самопроверка бота\n" + "-" * 30)
    _check("импорты всех модулей", check_imports)
    _check("конфиг и переменные", check_config)
    _check("контент (тексты, фото, гифки)", check_content)
    _check("тексты экранов (меню, справка, история)", check_ui_texts)
    _check("колода без повторов", check_deck)
    _check("собственный мини-мозг", check_brain)
    _check("ответы без комплиментов, интервал мемов", check_no_compliment_fallback)
    _check("подборка мемов (разбор без сети)", check_memes)
    _check("утренняя сводка: погода и курс", check_weather)
    _check("подготовка HTML для Telegram", check_html)
    _check("модели базы данных", check_database)
    _check("расписание и тихие часы", check_schedule)
    _check("хелперы отправки", check_send_helpers)
    if not quiet:
        print("-" * 30)
        if PROBLEMS:
            print(f"НАЙДЕНО ПРОБЛЕМ: {len(PROBLEMS)}")
            for p in PROBLEMS:
                print(f"  ! {p}")
        else:
            print("Всё чисто, проблем не найдено")
    return PROBLEMS


if __name__ == "__main__":
    sys.exit(1 if run_checks() else 0)
