"""
Авто-рассылки по ВСЕМ пользователям бота.

Периодические (молчат в тихие часы):
  * каждые SEND_GIF_MIN минут        - гифки с обнимашками
  * каждые SEND_POEM_MIN минут       - короткие милые стишки про Дашу
  * каждые SEND_CONFESSION_MIN минут - любовные признания
  * каждые SEND_PHOTO_MIN минут      - романтические фото

По времени суток (таймзона TIMEZONE):
  * MORNING_TIME (08:00) - доброе утро и победы в новом дне
  * NIGHT_TIME   (22:00) - спокойной ночи Даше и Аднану + напутствие на завтра

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
from managers import content
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
    MORNING_TIME,
    NIGHT_TIME,
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


async def _send_one(chat_id, *, text=None, animation=None, photo=None) -> bool:
    """
    Отправляет одно сообщение. Возвращает True при успехе.
    TelegramRetryAfter обрабатываем паузой, остальные ошибки - тихо пропускаем
    (пользователь мог заблокировать бота).
    """
    for attempt in (1, 2):
        try:
            if animation:
                await bot.send_animation(chat_id, animation, caption=text)
            elif photo:
                await bot.send_photo(chat_id, photo, caption=text)
            else:
                await bot.send_message(chat_id, text)
            return True
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
        except (TelegramForbiddenError, TelegramBadRequest):
            return False
        except Exception:
            cl.log("Reminds", "error", traceback.format_exc())
            return False
    return False


async def _broadcast(label: str, *, text=None, animation=None, photo=None,
                     probe_first: bool = False) -> tuple:
    """
    Разносит сообщение всем юзерам с паузами. Возвращает (отправлено, ошибок).
    probe_first=True - если ПЕРВЫЙ получатель не принял сообщение, прекращаем:
    так битая ссылка на медиа не порождает ошибку на каждом юзере.
    """
    targets = get_targets()
    if not targets:
        cl.log("Reminds", "info", f"{label}: отправлять некому (в БД нет юзеров)")
        return 0, 0

    sent = 0
    failed = 0
    for chat_id in targets:
        if await _send_one(chat_id, text=text, animation=animation, photo=photo):
            sent += 1
        else:
            failed += 1
            if probe_first and sent == 0:
                cl.log("Reminds", "info", f"{label}: первый получатель не принял, отменяю рассылку")
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


async def next_photo_url() -> str | None:
    """
    Ссылка на фото для рассылки.
    Специально НЕ проверяем доступность с нашего сервера: проверено, что Telegram
    скачивает ссылки, которые нам блокируют (picsum отвечает 403 нам, но Telegram
    их принимает). Нерабочую ссылку перехватит probe_first при первой отправке.
    """
    return await _photo_from_unsplash() or _photo_from_picsum()


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
    url = await next_photo_url()
    if url:
        sent, _ = await _broadcast("Фото", photo=url, text=content.next_poem(), probe_first=True)
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


async def _run_once_per_day(name: str, label: str, text: str) -> None:
    """
    Защита от дублей после рестарта: дату отправки храним в БД
    и помечаем ДО рассылки, чтобы падение посреди отправки не вызвало повтор.
    """
    today = now_local().strftime("%Y-%m-%d")
    if BotState.get_value(name) == today:
        return
    BotState.set_value(name, today)
    await _broadcast(label, text=text)


async def send_morning() -> None:
    await _run_once_per_day("last_morning", "Доброе утро", content.next_morning())


async def send_night() -> None:
    await _run_once_per_day("last_night", "Спокойной ночи", content.next_night())


async def send_test(chat_id) -> list:
    """
    Прогоняет по одному сообщению каждого типа на один чат.
    Нужно, чтобы не ждать час ради проверки. Возвращает список итогов.
    """
    results = []

    ok = await _send_one(chat_id, text=content.next_poem())
    results.append(f"стихи: {'ок' if ok else 'ошибка'}")

    ok = await _send_one(chat_id, text=content.next_confession())
    results.append(f"признания: {'ок' if ok else 'ошибка'}")

    gif_url = await get_gif_url()
    if gif_url:
        ok = await _send_one(chat_id, animation=gif_url, text=content.next_confession())
        src = "Giphy поиск" if giphy_token else "банк без ключа"
        results.append(f"гифки ({src}): {'ок' if ok else 'ошибка'}")
    else:
        results.append("гифки: пропуск (нет ни токена, ни гифок в банке)")

    photo_url = await next_photo_url()
    if photo_url:
        ok = await _send_one(chat_id, photo=photo_url, text=content.next_poem())
        results.append(f"фото: {'ок' if ok else 'ошибка'}")
    else:
        results.append("фото: пропуск (все источники недоступны)")

    ok = await _send_one(chat_id, text=content.next_morning())
    results.append(f"утро: {'ок' if ok else 'ошибка'}")

    ok = await _send_one(chat_id, text=content.next_night())
    results.append(f"ночь: {'ок' if ok else 'ошибка'}")

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
