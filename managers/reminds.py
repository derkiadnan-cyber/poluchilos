"""
Авто-рассылки по ВСЕМ пользователям бота.

Периодические (молчат в тихие часы):
  * каждые SEND_GIF_MIN минут        - гифки с обнимашками
  * каждые SEND_POEM_MIN минут       - короткие милые стишки про Дашу
  * каждые SEND_CONFESSION_MIN минут - любовные признания
  * каждые SEND_PHOTO_MIN минут      - романтические фото
  * каждые MEME_MIN минут            - самый смешной мем дня (по голосам)

По времени суток (таймзона TIMEZONE):
  * MORNING_TIME (08:00)  - доброе утро и победы в новом дне
  * WEATHER_TIME (08:30)  - погода в Минске на весь день + курс доллара к BYN
  * NIGHT_TIME   (22:00)  - спокойной ночи Даше и Аднану + напутствие на завтра

Интервалы, времена и таймзона настраиваются через переменные окружения
(см. storage/config.py). Сам контент - в managers/content.py.
"""

import asyncio
import random
import traceback
from datetime import datetime
from zoneinfo import ZoneInfo

import aiohttp
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)

from db import User, BotState
from managers import content, memes, weather
import utils.custom_logger as cl
from storage.config import (
    bot,
    giphy_token,
    unsplash_key,
    AUTOSEND,
    TIMEZONE,
    SEND_POEM_MIN,
    SEND_CONFESSION_MIN,
    SEND_PHOTO_MIN,
    SEND_GIF_MIN,
    MEME_MIN,
    MEME_ENABLED,
    MORNING_TIME,
    NIGHT_TIME,
    WEATHER_ENABLED,
    WEATHER_TIME,
    QUIET_HOURS,
    QUIET_FROM,
    QUIET_TO,
)

TZ = ZoneInfo(TIMEZONE)

TICK_SECONDS = 20          # как часто проверяем расписание
SEND_PAUSE = 0.15          # пауза между сообщениями разным юзерам (антфлуд)
HTTP_TIMEOUT = 15          # таймаут запросов к Giphy/хостингу фото
GIPHY_API_URL = "https://api.giphy.com/v1/gifs/search"


def now_local() -> datetime:
    """Текущее время в таймзоне бота (Railway живёт в UTC, поэтому не datetime.now())."""
    return datetime.now(TZ)


def _minutes_of_day(dt: datetime) -> int:
    return dt.hour * 60 + dt.minute


def _time_reached(dt: datetime, target: tuple) -> bool:
    """Наступило ли уже время target (ЧЧ:ММ) этого дня."""
    return _minutes_of_day(dt) >= target[0] * 60 + target[1]


def is_quiet_now() -> bool:
    """Тихие часы: периодические рассылки не должны будить людей ночью."""
    if not QUIET_HOURS:
        return False
    cur = _minutes_of_day(now_local())
    start = QUIET_FROM[0] * 60 + QUIET_FROM[1]
    end = QUIET_TO[0] * 60 + QUIET_TO[1]
    if start <= end:
        return start <= cur < end
    # интервал через полночь (например 22:30 - 07:30)
    return cur >= start or cur < end


def get_targets() -> list:
    """Список уникальных tg_id всех, кто когда-либо нажал /start."""
    ids = []
    seen = set()
    for user in User.all():
        user: User
        if user.tg_id and user.tg_id not in seen:
            seen.add(user.tg_id)
            ids.append(user.tg_id)
    return ids


# Результаты одной отправки. Разные причины отказа надо различать:
# юзер заблокировал бота - это нормально и НЕ повод отменять рассылку,
# а вот битая ссылка на медиа - повод остановиться и не позориться перед всеми.
OK = "ok"
BLOCKED = "blocked"          # юзер заблокировал бота / удалил аккаунт
MEDIA_ERROR = "media_error"  # Telegram не смог скачать гифку или фото
FAILED = "failed"            # всё остальное

# Счётчики для /status: сколько людей отписалось, сколько раз медиа не пришло
stats = {"sent": 0, "blocked": 0, "media_error": 0, "failed": 0}
# Кэш «уже отправлено сегодня», чтобы не дёргать SQLite каждые 20 секунд
_daily_cache = {}


async def _send_one(chat_id, *, text=None, animation=None, photo=None) -> str:
    """
    Отправляет одно сообщение и возвращает причину успеха/отказа (OK/BLOCKED/...).
    TelegramRetryAfter обрабатываем паузой, остальные ошибки - тихо пропускаем.
    """
    media = bool(animation or photo)
    for attempt in (1, 2):
        try:
            if animation:
                await bot.send_animation(chat_id, animation, caption=text)
            elif photo:
                await bot.send_photo(chat_id, photo, caption=text)
            else:
                await bot.send_message(chat_id, text)
            stats["sent"] += 1
            return OK
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
        except TelegramForbiddenError:
            stats["blocked"] += 1
            return BLOCKED
        except TelegramBadRequest as e:
            # Telegram отвечает «failed to get HTTP URL content», когда ссылка
            # на медиа не работает. Такое повторять бессмысленно.
            if media and "url" in str(e).lower():
                stats["media_error"] += 1
                return MEDIA_ERROR
            stats["failed"] += 1
            return FAILED
        except Exception:
            cl.log("Reminds", "error", traceback.format_exc())
            stats["failed"] += 1
            return FAILED
    stats["failed"] += 1
    return FAILED


async def _broadcast(label: str, *, text=None, animation=None, photo=None,
                     probe_first: bool = False) -> tuple:
    """
    Разносит сообщение всем юзерам с паузами. Возвращает (отправлено, пропущено).
    probe_first=True - прекращаем рассылку, только если ПЕРВОМУ получателю не
    зашло именно медиа (битая ссылка). Если же первый просто заблокировал бота,
    это не повод лишать сообщений остальных.
    """
    targets = get_targets()
    if not targets:
        cl.log("Reminds", "info", f"{label}: отправлять некому (в БД нет юзеров)")
        return 0, 0

    sent = 0
    failed = 0
    for chat_id in targets:
        result = await _send_one(chat_id, text=text, animation=animation, photo=photo)
        if result == OK:
            sent += 1
        else:
            failed += 1
            if probe_first and sent == 0 and result == MEDIA_ERROR:
                cl.log("Reminds", "info",
                       f"{label}: Telegram не забрал медиа, отменяю рассылку")
                return 0, failed
        await asyncio.sleep(SEND_PAUSE)

    cl.log("Reminds", "info", f"{label}: отправлено {sent}, пропущено {failed} (из {len(targets)})")
    return sent, failed


async def _fetch_json(url: str, params: dict = None):
    timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, params=params) as resp:
            resp.raise_for_status()
            return await resp.json()


async def _photo_from_unsplash() -> str | None:
    """Unsplash API: романтическое фото по тегу. Нужен бесплатный ключ."""
    if not unsplash_key:
        return None
    try:
        data = await _fetch_json(
            "https://api.unsplash.com/photos/random",
            params={
                "query": content.next_photo_tag(),
                "orientation": "landscape",
                "content_filter": "high",
                "client_id": unsplash_key,
            },
        )
        return (data.get("urls") or {}).get("regular")
    except Exception:
        cl.log("Reminds", "error", traceback.format_exc())
        return None


def _photo_from_picsum() -> str:
    """
    Picsum: случайное качественное фото без ключа.
    Проверено: Telegram успешно забирает эти ссылки.
    """
    return f"https://picsum.photos/seed/{random.randint(1, 999999)}/1000/700"


async def next_photo_url() -> tuple:
    """
    Ссылка на фото для рассылки и имя источника: (url, source).
    Цепочка: Unsplash (только если задан ключ, зато строго по романтическому тегу)
    -> встроенный банк ROMANTIC_PHOTOS (тема подтверждена именем файла, ключ не нужен)
    -> picsum (последний запасной вариант).
    Специально НЕ проверяем доступность с нашего сервера: проверено, что Telegram
    скачивает ссылки, которые нам блокируют (picsum отвечает 403 нам, но Telegram
    их принимает). Нерабочую ссылку перехватит probe_first при первой отправке.
    """
    url = await _photo_from_unsplash()
    if url:
        return url, "Unsplash по теме"
    try:
        return content.next_romantic_photo(), "банк фото"
    except ValueError:
        return _photo_from_picsum(), "picsum"


async def get_gif_url() -> str | None:
    """
    Ссылка на случайную гифку с обнимашками.
    С GIPHY_TOKEN - свежий поиск по запросу, без токена - из проверенного банка.
    """
    if giphy_token:
        query = content.next_gif_query()
        try:
            data = await _fetch_json(GIPHY_API_URL, params={
                "api_key": giphy_token,
                "q": query,
                "limit": 25,
                "rating": "pg-13",
                "lang": "en",
            })
            results = data.get("data") or []
            if results:
                return random.choice(results)["images"]["original"]["gif_url"]
            cl.log("Reminds", "info", "Giphy ничего не нашёл, беру гифку из банка")
        except Exception:
            cl.log("Reminds", "error", traceback.format_exc())
    return content.next_hug_gif()


async def send_poems() -> None:
    """Короткие милые стишки про Дашу."""
    await _broadcast("Стихи", text=content.next_poem())


async def send_confessions() -> None:
    """Любовные признания."""
    await _broadcast("Признания", text=content.next_confession())


async def send_photos() -> None:
    """Романтические фото. Подписью служит стишок, чтобы фото не уходило голым."""
    url, source = await next_photo_url()
    if url:
        sent, _ = await _broadcast(f"Фото ({source})", photo=url,
                                   text=content.next_poem(), probe_first=True)
        if sent:
            return
    # Медиа не дошло - лучше отправим текст, чем промолчим
    cl.log("Reminds", "error", "Фото отправить не удалось, отправляю стихи")
    await _broadcast("Фото (замена)", text=content.next_poem())


async def send_gifs() -> None:
    """Гифки с обнимашками. Подпись - признание, чтобы гифка не уходила голой."""
    gif_url = await get_gif_url()
    caption = content.next_confession()
    if gif_url:
        sent, _ = await _broadcast("Гифки", animation=gif_url, text=caption, probe_first=True)
        if sent:
            return
        # Гифку не приняли (например, ссылка протухла) - шлём хотя бы текст
        cl.log("Reminds", "error", "Гифку отправить не удалось, отправляю текст")
    await _broadcast("Гифки (замена)", text=caption)


async def send_memes() -> None:
    """
    Самый смешной мем из свежей подборки (managers/memes.py).
    Вместо мема текст не присылаем: «мем не загрузился» - это не мем.
    Если подборка пуста (нет сети), просто молчим этот час.
    """
    meme = await memes.next_meme()
    if not meme:
        cl.log("Reminds", "info", "Мемы: брать нечего (нет сети?), пропускаю час")
        return

    caption = f"{content.next_meme_caption()} ({meme['ups']} голосов) 😂"
    label = f"Мемы ({meme['ups']} голосов, {meme['sub']})"
    if meme["animation"]:
        sent, _ = await _broadcast(label, animation=meme["url"], text=caption,
                                   probe_first=True)
    else:
        sent, _ = await _broadcast(label, photo=meme["url"], text=caption,
                                   probe_first=True)
    if not sent:
        cl.log("Reminds", "warning",
               "Мемы: Telegram не забрал картинку, в следующий раз возьму другую")


async def send_meme_to(chat_id) -> bool:
    """
    Мем по просьбе в одном чате (написала «мем» - принесла сразу).
    Возвращает True, только если картинка реально ушла: иначе caller сам
    ответит текстом и не будет выглядеть молчуном.
    """
    meme = await memes.next_meme()
    if not meme:
        return False
    caption = f"{content.next_meme_caption()} ({meme['ups']} голосов) 😂"
    if meme["animation"]:
        result = await _send_one(chat_id, animation=meme["url"], text=caption)
    else:
        result = await _send_one(chat_id, photo=meme["url"], text=caption)
    return result == OK


def _should_run_today(name: str) -> bool:
    """
    «Ровно один раз в сутки» для утренних рассылок.
    Дату держим в памяти процесса, а в БД заглядываем только один раз за день -
    иначе цикл каждые 20 секунд ходил бы в SQLite без всякого смысла.
    Отметку ставим ДО рассылки, чтобы падение посреди отправки не вызвало повтор.
    """
    today = now_local().strftime("%Y-%m-%d")
    if _daily_cache.get(name) == today:
        return False
    if BotState.get_value(name) == today:
        _daily_cache[name] = today
        return False
    BotState.set_value(name, today)
    _daily_cache[name] = today
    return True


async def _run_once_per_day(name: str, label: str, text: str) -> None:
    """«Доброе утро» и «спокойной ночи» должны приходить ровно раз в сутки."""
    if not _should_run_today(name):
        return
    await _broadcast(label, text=text)


async def send_morning() -> None:
    await _run_once_per_day("last_morning", "Доброе утро", content.next_morning())


async def send_night() -> None:
    await _run_once_per_day("last_night", "Спокойной ночи", content.next_night())


async def send_weather(chat_id=None) -> bool:
    """
    Утренняя сводка: погода в Минске на весь день + курс доллара (managers/weather.py).
    Приходит раз в сутки в WEATHER_TIME. Если источники молчат - молчим и мы:
    выдуманная погода хуже, чем её отсутствие, а «доброе утро» придёт как обычно.
    chat_id указан - отправляем только ему (тест из админ-панели).
    """
    if chat_id is not None:
        text = await weather.morning_digest()
        if not text:
            return False
        return await _send_one(chat_id, text=text) == OK

    if not _should_run_today("last_weather"):
        return False
    text = await weather.morning_digest()
    if not text:
        # Отметку на сегодня уже поставили, но лучше одно молчание в день,
        # чем десять попыток подряд по кругу каждые 20 секунд
        cl.log("Reminds", "warning", "Погода: источники молчат, сегодня не приходилось")
        return False
    await _broadcast("Погода и курс", text=text)
    return True


async def send_test(chat_id) -> list:
    """
    Прогоняет по одному сообщению каждого типа на один чат.
    Нужно, чтобы не ждать час ради проверки. Возвращает список итогов.
    """
    results = []

    async def one(label, **kwargs):
        result = await _send_one(chat_id, **kwargs)
        why = {OK: "ок", BLOCKED: "чат не принял", MEDIA_ERROR: "медиа не загрузилось",
               FAILED: "ошибка"}[result]
        results.append(f"{label}: {why}")

    await one("стихи", text=content.next_poem())
    await one("признания", text=content.next_confession())

    gif_url = await get_gif_url()
    if gif_url:
        src = "Giphy поиск" if giphy_token else "банк без ключа"
        await one(f"гифки ({src})", animation=gif_url, text=content.next_confession())
    else:
        results.append("гифки: пропуск (нет ни токена, ни гифок в банке)")

    photo_url, photo_source = await next_photo_url()
    if photo_url:
        await one(f"фото ({photo_source})", photo=photo_url, text=content.next_poem())
    else:
        results.append("фото: пропуск (все источники недоступны)")

    await one("утро", text=content.next_morning())
    await one("ночь", text=content.next_night())

    # Сводка утра идёт одной картиной: погода + доллар. Считаем её честно,
    # не дожидаясь 08:30, иначе проверить «а погода-то работает?» нельзя.
    digest = await weather.morning_digest()
    if digest:
        await one("погода + курс (08:30)", text=digest)
    else:
        results.append("погода + курс: пропуск (Open-Meteo и NBRB не ответили)")

    meme = await memes.next_meme()
    if meme:
        caption = f"{content.next_meme_caption()} ({meme['ups']} голосов) 😂"
        label = f"мем ({meme['ups']} голосов, {meme['sub']})"
        if meme["animation"]:
            await one(label, animation=meme["url"], text=caption)
        else:
            await one(label, photo=meme["url"], text=caption)
    else:
        results.append("мемы: пропуск (подборка пуста - нет сети?)")

    return results


async def remindsManager():
    """Главный цикл рассылок. Запускается как фоновая задача из bot.py."""
    if AUTOSEND:
        cl.log("Reminds Manager", "info",
               f"🟢 Авто-рассылки ВКЛЮЧЕНЫ | таймзона {TIMEZONE} | "
               f"утро {MORNING_TIME[0]:02d}:{MORNING_TIME[1]:02d} | "
               f"ночь {NIGHT_TIME[0]:02d}:{NIGHT_TIME[1]:02d} | "
               f"гифки {SEND_GIF_MIN}м | стихи {SEND_POEM_MIN}м | "
               f"признания {SEND_CONFESSION_MIN}м | фото {SEND_PHOTO_MIN}м | "
               f"{'мемы ' + str(MEME_MIN) + 'м' if MEME_ENABLED else 'мемы выкл'} | "
               f"{'сводка утра в %02d:%02d' % WEATHER_TIME if WEATHER_ENABLED else 'сводка утра выкл'} | "
               f"тихие часы {'вкл' if QUIET_HOURS else 'выкл'}")
    else:
        cl.log("Reminds Manager", "info", "🔒 Авто-рассылки ОТКЛЮЧЕНЫ (AUTOSEND != on)")

    periods = {
        "gif": SEND_GIF_MIN * 60,
        "poem": SEND_POEM_MIN * 60,
        "confession": SEND_CONFESSION_MIN * 60,
        "photo": SEND_PHOTO_MIN * 60,
    }
    jobs = {
        "gif": send_gifs,
        "poem": send_poems,
        "confession": send_confessions,
        "photo": send_photos,
    }
    # Мемы - отдельная гонка: интервал свой (55 минут по умолчанию), и их
    # можно выключить целиком переменной MEME_ENABLED=off
    if MEME_ENABLED:
        periods["meme"] = MEME_MIN * 60
        jobs["meme"] = send_memes
    # Старт таймеров с текущего момента: первая рассылка - только через полный интервал
    last_run = {name: now_local() for name in jobs}

    while True:
        try:
            if AUTOSEND:
                now = now_local()

                # Фиксированные времена (не зависят от тихих часов)
                if _time_reached(now, MORNING_TIME):
                    await send_morning()
                if _time_reached(now, NIGHT_TIME):
                    await send_night()
                # Сводка утра: погода + доллар. В тихие часы не сработает,
                # но и просрочкой не выйдет - тихо закончится в 07:30,
                # а в 08:30 своё возьмёт
                if WEATHER_ENABLED and _time_reached(now, WEATHER_TIME) and not is_quiet_now():
                    await send_weather()

                # Периодические рассылки
                if not is_quiet_now():
                    for name, job in jobs.items():
                        if (now - last_run[name]).total_seconds() >= periods[name]:
                            await job()
                            last_run[name] = now

            await asyncio.sleep(TICK_SECONDS)
        except Exception:
            cl.log("Reminds Manager", "error", traceback.format_exc())
            await asyncio.sleep(TICK_SECONDS)
