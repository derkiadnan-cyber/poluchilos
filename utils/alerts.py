"""
Доставка тревог администраторам.

Зачем отдельный модуль. Раньше логгер сам дёргал Telegram через синхронный
requests.post прямо внутри обработчика сообщения. Это значило, что на время
каждой ошибки весь бот останавливался: event loop не может отвечать другим
пользователям, пока ждёт сетевой запрос. Плюс при сбое Telegram исключение
вылетало наружу из обработчика, который и так разбирал аварию, а при потоке
ошибок админ получал шквал одинаковых уведомлений.

Здесь всё по-другому:
  * submit() - синхронный и мгновенный, просто кладёт текст в очередь;
  * фоновая задача тихо забирает очередь и отправляет через сессию aiogram,
    не блокируя основной код;
  * троттлинг по разделу: одинаковые тревоги слипаются в одно сообщение,
    а не сыплются сотней;
  * ни одно исключение отсюда наружу не уходит - логгер не должен ронять бот.
"""

import asyncio
import time
from collections import defaultdict, deque

MAX_QUEUE = 100        # сколько тревог поместить, если админ не читает
MAX_BATCH = 8          # сколько тревог слить в одно сообщение
DEFAULT_GAP = 60       # секунд между уведомлениями об одном разделе
DROPPED_NOTE = "…и ещё {n} похожих сообщений пропущено"

_queue = deque(maxlen=MAX_QUEUE)
_counts = defaultdict(int)     # тревог с последней отправки по разделам
_last_sent = defaultdict(float)
_gaps = {}
_worker_task = None


def submit(department: str, text: str, gap: int = DEFAULT_GAP) -> None:
    """Кладёт тревогу в очередь. Никогда не блокируется и не бросает исключений."""
    try:
        _counts[department] += 1
        _gaps[department] = gap
        if len(_queue) == _queue.maxlen:
            _queue.popleft()          # старое жертвуем свежим
        _queue.append((department, text))
        _ensure_worker()
    except Exception:
        # Логгер не имеет права ронять бот ни при каких обстоятельствах
        pass


def _ensure_worker() -> None:
    """Поднимает доставщика, если он уснул. Без работающего loop - тихо выходим."""
    global _worker_task
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if _worker_task is None or _worker_task.done():
        _worker_task = loop.create_task(_deliver())


def pending() -> int:
    """Сколько тревог ещё не разослано (для /status)."""
    return len(_queue)


def _compose(department: str, batch: list) -> str:
    head = f"⚠️ {department} · {len(batch)} шт" if len(batch) > 1 else f"⚠️ {department}"
    body = "\n---\n".join(batch[:MAX_BATCH])
    extra = len(batch) - MAX_BATCH
    if extra > 0:
        body += "\n" + DROPPED_NOTE.format(n=extra)
    return f"{head}\n{body}"[:3900]


async def _deliver() -> None:
    """Разбирает очередь, соблюдая паузы между уведомлениями одного раздела."""
    try:
        # Ленивый импорт: модуль логов не должен тянуть бота на этапе импорта
        from storage.config import admins, bot
    except Exception:
        return

    while _queue:
        try:
            department, _ = _queue[0]
            wait = _gaps.get(department, DEFAULT_GAP) - (time.monotonic() - _last_sent[department])
            if wait > 0:
                await asyncio.sleep(min(wait, 5))
                continue

            batch, sent_count = [], 0
            while _queue and len(batch) < MAX_BATCH and _queue[0][0] == department:
                batch.append(_queue.popleft()[1])
            text = _compose(department, batch)

            for admin_id in admins:
                try:
                    await bot.send_message(admin_id, text)
                    sent_count += 1
                except Exception:
                    pass   # админ мог заблокировать бота - не наша проблема

            _last_sent[department] = time.monotonic()
            _counts[department] = 0
        except asyncio.CancelledError:
            raise
        except Exception:
            # Доставка тревог не должна валить ни основную задачу, ни себя
            await asyncio.sleep(5)
