"""
Мемы по расписанию: раз в MEME_MIN минут бот приносит самый смешной мем.

Честно про Instagram. Брать оттуда фото нельзя, и это не лень, а запрет:
у Instagram нет публичного API чужих постов, есть только Graph API для
СОБСТВЕННОГО бизнес-аккаунта с токеном, который выдаёт админ аккаунта.
Чужие лайки и комментарии через него не отдаются, а «скрейпинг» ломается об
логин-страницу и приводит к бану аккаунта в течение пары дней. Поэтому
берём то, где рейтинг доступен открыто и без ключей.

Источник - meme-api.com (открытый, без регистрации и без ключей, отдаёт
посты из сабреддитов вместе с их рейтингом). «Количество лайков» здесь - это
upvotes поста: чем их больше, тем выше он в подборке. Сортируем именно по
ним и берём верхнюю половину. Количество комментариев meme-api в этом режиме
не отдаёт (приходит null), поэтому комментарии в вес не берём - выдумывать
цифры не будем.

Список сабреддитов заведомо русскоязычный (r/pikabu и компания): в больших
англоязычных r/memes подборка смешнее, но пользователю нужны мемы на русском.
Русские сабреддиты маленькие - топ там это ~200 голосов, а не 40 000, поэтому
и порог MEME_MIN_UPS заметно ниже.

Механика:
  * берём ТОЛЬКО русскоязычные посты: в подписи обязана быть кириллица.
    Без этого фильтра r/russian_memes присылает «Russian pickachu» с подписью
    на английском, а r/pikabu такой проблемы не имеет вовсе;
  * пул из MEME_POOL_SIZE мемов живёт в памяти MEME_TTL секунд - не дёргаем
    сеть каждые 55 минут и не зависим от неё в момент рассылки;
  * 18+, спойлеры и не-картинки отсекаются, мемы с меньше MEME_MIN_UPS
    голосов считаются несмешными;
  * уже отправленное не повторяем (память последних RECENT_LIMIT ссылок);
  * если сети нет и пул пуст - рассылка мемов просто пропускается: молчание
    лучше, чем «не удалось загрузить картинку» посреди ночи.
"""

import asyncio
import random
import re
import time
from collections import deque

import aiohttp

from storage.config import (MEME_MIN_UPS, MEME_POOL_SIZE, MEME_RUSSIAN_ONLY,
                            MEME_SUBREDDITS)
import utils.custom_logger as cl

API_URL = "https://meme-api.com/gimme/{subreddit}/{count}"
# Reddit и его прокси режут запросы без нормального User-Agent
USER_AGENT = "romance-bot/1.0 (personal telegram bot)"

HTTP_TIMEOUT = 15
MEME_TTL = 40 * 60        # пул протухает быстрее, чем успевает надоесть
FETCH_COUNT = 30          # сколько постов просим у одного сабреддита
RECENT_LIMIT = 200        # сколько отправленных ссылок помнить
TOP_SHARE = 0.6           # берём верхнюю часть подборки по количеству голосов

# расширения, которые Telegram точно переварит как фото или гифку
_PHOTO_EXT = (".jpg", ".jpeg", ".png")
_GIF_EXT = (".gif",)

# Русскоязычный мем определяем по подписи поста: в русскоязычных сабредитах
# она по-русски почти всегда. Английский текст в подписи = мем не наш.
_CYRILLIC = re.compile("[а-яё]", re.IGNORECASE)

_pool = []                 # [{"url","animation","ups","title","sub"}]
_recent = deque(maxlen=RECENT_LIMIT)
_fetched_at = 0.0
_lock = asyncio.Lock()

# Статистика для /status: сколько раз реально нашли и сколько раз молчали
stats = {"sent": 0, "no_internet": 0, "nothing_found": 0, "not_russian": 0}


def _parse(items) -> list:
    """Превращает ответ API в наши мемы, отбрасывая мусор и откровенное 18+."""
    memes = []
    for post in items or []:
        url = (post.get("url") or "").strip()
        if not url:
            continue
        animation = url.lower().endswith(_GIF_EXT)
        if not url.lower().endswith(_PHOTO_EXT + _GIF_EXT):
            # видео (.mp4/.webm), битые ссылки и прочее не отправляем
            continue
        if post.get("nsfw") or post.get("spoiler"):
            continue
        title = (post.get("title") or "").strip()[:120]
        if MEME_RUSSIAN_ONLY and not _CYRILLIC.search(title):
            # Подпись без кириллицы - мем англоязычный, пользователю он не нужен
            stats["not_russian"] += 1
            continue
        try:
            ups = int(post.get("ups") or post.get("score") or 0)
        except (TypeError, ValueError):
            ups = 0
        if ups < MEME_MIN_UPS:
            continue
        memes.append({
            "url": url,
            "animation": animation,
            "ups": ups,
            "title": title,
            "sub": post.get("subreddit") or "",
        })
    return memes


async def _fetch_subreddit(session, subreddit: str) -> list:
    url = API_URL.format(subreddit=subreddit, count=FETCH_COUNT)
    async with session.get(url, headers={"User-Agent": USER_AGENT}) as resp:
        if resp.status != 200:
            cl.log("Memes", "warning", f"{subreddit}: HTTP {resp.status}")
            return []
        data = await resp.json(content_type=None)
    return _parse(data.get("memes"))


async def _refill() -> None:
    """
    Обновляет пул. Пробуем сабреддиты по очереди: если первый лежит или
    отдал одну ерунду, берём следующий.
    """
    global _pool, _fetched_at
    timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT)
    collected = []
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for subreddit in MEME_SUBREDDITS:
            try:
                collected.extend(await _fetch_subreddit(session, subreddit))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                cl.log("Memes", "warning",
                       f"{subreddit}: сеть не ответила ({type(exc).__name__})")
            # Хватит и одного полного списка: лишние запросы ни к чему
            if len(collected) >= MEME_POOL_SIZE:
                break

    if not collected:
        stats["no_internet"] += 1
        return

    # Отбор «чем больше лайков, тем лучше»: верхняя часть по голосам,
    # и только из неё перемешиваем, чтобы не показывать один и тот же топ.
    collected.sort(key=lambda m: m["ups"], reverse=True)
    top = collected[:max(1, int(len(collected) * TOP_SHARE))]
    random.shuffle(top)

    fresh = [m for m in top if m["url"] not in _recent]
    if not fresh:
        # Всё уже отправляли - берём что есть, но очищаем память отправленного,
        # иначе тот же мем всплыл бы снова уже через час
        fresh = top
        _recent.clear()
    _pool = fresh[:MEME_POOL_SIZE]
    _fetched_at = time.monotonic()
    cl.log("Memes", "info", f"обновил подборку: {len(_pool)} мемов, топ "
                            f"{top[0]['ups']} голосов ({top[0]['sub']})")


async def next_meme() -> dict | None:
    """
    Возвращает следующий мем: {"url", "animation", "ups", "title", "sub"}
    либо None, если найти нечего (сети нет, а пул пуст или весь отправлен).
    """
    async with _lock:
        if _expired() or not _pool:
            await _refill()
        while _pool:
            meme = _pool.pop(0)
            if meme["url"] in _recent:
                continue
            _recent.append(meme["url"])
            stats["sent"] += 1
            return meme
    stats["nothing_found"] += 1
    return None


def _expired() -> bool:
    return time.monotonic() - _fetched_at >= MEME_TTL


def status_line() -> str:
    """Строчка для /status: чем отвечаем и почему иногда молчим."""
    if _fetched_at:
        age = int(time.monotonic() - _fetched_at)
        pool_age = f"{age // 60} мин назад"
    else:
        pool_age = "ещё не грузил"
    lang = "только русские" if MEME_RUSSIAN_ONLY else "любые"
    return (f"мемы ({lang}): пул {len(_pool)}, обновлён {pool_age} | отправлено "
            f"{stats['sent']}, без сети {stats['no_internet']}, пусто "
            f"{stats['nothing_found']}, не по-русски {stats['not_russian']}")
