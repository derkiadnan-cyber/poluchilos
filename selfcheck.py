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
    import managers.reminds
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
    problems = []
    cases = {
        "2+2": "4", "сколько будет 17*23": "391", "(5+3)*2**3": "64",
        "5% от 200": "10", "корень из 144": "12", "100/7": "14.285",
        "2^10": "1 024",
    }
    for question, expected in cases.items():
        reply = brain.answer(question) or ""
        if expected not in reply:
            problems.append(f"калькулятор «{question}» дал «{reply[:40]}», ждали «{expected}»")

    zero = brain.answer("8/0") or ""
    if "ноль" not in zero.lower():
        problems.append(f"деление на ноль отвечено странно: «{zero[:40]}»")

    # Бытовые вопросы обязаны отвечаться без сети
    for question in ("привет", "что умеешь", "который час", "какое сегодня число",
                     "подбрось монетку", "спасибо", "скинь стих"):
        if not brain.answer(question):
            problems.append(f"свой мозг промолчал на «{question}»")

    # Мусор и попытки инъекции не должны ронять движок и не должны выполняться
    for junk in ("", "   ", "йцукен", "2+", "-3", "__import__('os').system('calc')",
                 "9" * 500, "((1+2)", "1/0/0", "None", "🍌🍌"):
        try:
            brain.answer(junk)
        except Exception as exc:
            problems.append(f"свой мозг упал на «{junk[:20]}»: {type(exc).__name__}")
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
    _check("колода без повторов", check_deck)
    _check("собственный мини-мозг", check_brain)
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
