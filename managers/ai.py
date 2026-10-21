"""
Ответы на обычные сообщения пользователя. Каскад из трёх каналов.

    1. DeepSeek      - если задан DEEPSEEK_API_KEY (платно, но быстро и без лимитов)
    2. Pollinations  - бесплатно и БЕЗ КЛЮЧА вообще, OpenAI-совместимый API.
                       У бесплатного тарифа лимит 1 ответ в 30 секунд на IP,
                       поэтому стучимся не чаще - иначе получаем HTTP 402.
    3. Свой мозг     - managers/brain.py: считает, знает дату, отвечает про бота.
                       Работает всегда: без ключей, без сети, без лимитов.

Бот не должен молчать ни при каких условиях: собственный движок отвечает и с
пустым интернетом, и при исчерпанном лимите бесплатного канала. Комплименты
как заглушку убрали - вместо них честный ответ по существу с лёгкой нежностью.

Ключи берутся из окружения (локально storage/.env, в облаке Railway Variables).
В репозитории ключей нет и быть не должно.
"""

import asyncio
import html as html_lib
import re
import time
import traceback
from collections import defaultdict, deque

import aiohttp

from managers import brain, weather
from managers.content import AI_SYSTEM_PROMPT
from storage.config import (
    AI_ENABLED, AI_MAX_TOKENS, AI_TIMEOUT, WEATHER_ENABLED,
    deepseek_key, deepseek_model, pollinations_model,
)
import utils.custom_logger as cl

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
POLLINATIONS_URL = "https://text.pollinations.ai/openai"

HISTORY_SIZE = 10          # реплик на один чат (user + assistant), ~5 вопросов
MAX_INPUT_CHARS = 2000     # длинные сообщения режем: лишние токены нам не нужны
MAX_ANSWER_CHARS = 3500    # лимит Telegram 4096, берём с запасом
MIN_GAP_SECONDS = 1.0      # антифлуд: не чаще одного ответа в секунду на чат
POLL_FREE_GAP = 31         # бесплатный Pollinations отдаёт 1 ответ в 30 секунд на IP
MAX_CHATS_IN_MEMORY = 500  # чтобы память контейнера не росла бесконечно

# Ошибки, которые означают «сеть не ответила»: это не баг, а погода,
# поэтому воркер не зовём, пишем одной строкой.
NETWORK_ERRORS = (aiohttp.ClientError, asyncio.TimeoutError)

TEXT_BUSY = "Уже думаю над твоим прошлым сообщением 💋 Секунду, я рядом"
TEXT_UNKNOWN = ("Не нашла ответа ни в себе, ни в сети 🙈 Напиши «что умеешь» — "
                "расскажу, а так я рядом и никуда не денусь 💋")

last_source = "—"          # какой канал ответил последним - видно в /status у админа
_poll_ok_at = 0.0          # когда в последний раз успешно ответил Pollinations
_poll_blocked_until = 0.0  # до какого момента не пробуем (ловили лимит или отказ)

_history = defaultdict(lambda: deque(maxlen=HISTORY_SIZE))
_busy = set()
_last_call = {}


# ===== markdown из ответа модели -> Telegram HTML =====
# Бот по умолчанию шлёт HTML, поэтому ответ модели нужно экранировать,
# иначе случайная скобка в тексте уронит отправку с TelegramBadRequest.
_LINK = re.compile(r"\[([^\]\n]+)\]\(([^)\s]+)\)")
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_BOLD = re.compile(r"\*\*(.+?)\*\*|__(.+?)__", re.S)
_ITALIC = re.compile(r"(?<![\w*])\*([^*\n]+)\*(?!\*)")
_HEADER = re.compile(r"^\s*#{1,6}\s*(.+?)\s*$", re.M)
_BULLET = re.compile(r"^\s*[-*+]\s+", re.M)
_RULE = re.compile(r"^[ \t]*[-*_]{3,}[ \t]*$", re.M)
_BLANK = re.compile(r"\n{3,}")


def _visible(text: str) -> str:
    """Тот же текст без HTML-тегов: нужен, чтобы понять, есть ли в ответе смысл."""
    return re.sub("<[^>]+>", " ", text).strip()


def _inline_to_html(segment: str) -> str:
    """Превращает markdown из одного текстового куска в теги Telegram."""
    text = html_lib.escape(segment)
    text = _LINK.sub(r"\1 (\2)", text)
    text = _INLINE_CODE.sub(r"<code>\1</code>", text)
    text = _BOLD.sub(lambda m: f"<b>{m.group(1) or m.group(2)}</b>", text)
    text = _ITALIC.sub(r"<i>\1</i>", text)
    text = _HEADER.sub(r"<b>\1</b>", text)
    text = _BULLET.sub("• ", text)
    text = _RULE.sub("", text)
    return text


def _safe_truncate(text: str) -> str:
    """
    Режет по лимиту Telegram так, чтобы не остаться с куском тега посередине:
    незакрытый <b> или <pre> Telegram считает ошибкой разметки, и сообщение
    просто не уйдёт.
    """
    if len(text) <= MAX_ANSWER_CHARS:
        return text
    cut = text[:MAX_ANSWER_CHARS]
    if cut.rfind("<") > cut.rfind(">"):
        cut = cut[:cut.rfind("<")]
    for tag in ("pre", "code", "b", "i"):
        opened = len(re.findall(rf"<{tag}>", cut))
        closed = len(re.findall(rf"</{tag}>", cut))
        if opened > closed:
            cut += f"</{tag}>" * (opened - closed)
    return cut.rstrip() + "…"


def to_telegram_html(model_text: str) -> str:
    """
    Экранирует ответ модели и переводит markdown в Telegram HTML.
    Куски между ``` считаются кодом и внутрь <pre> идут без обработки.
    """
    parts = []
    for index, segment in enumerate(model_text.split("```")):
        if index % 2 == 1:
            # строка с названием языка после ``` нам не нужна
            code = segment.split("\n", 1)[1] if "\n" in segment else segment
            parts.append(f"<pre>{html_lib.escape(code.strip())}</pre>")
        else:
            parts.append(_inline_to_html(segment))
    text = "".join(parts).strip()
    # Модель могла выдать пустой блок кода (только ```) - такая карточка
    # улетела бы в Telegram пустой, вырезаем её.
    text = re.sub(r"<pre>\s*</pre>", "", text).strip()
    return _safe_truncate(_BLANK.sub("\n\n", text))


# ===== ХРАНЕНИЕ ДИАЛОГА =====
def _remember(chat_id, role: str, text: str) -> None:
    if len(_history) > MAX_CHATS_IN_MEMORY:
        _history.clear()
        _busy.clear()
        _last_call.clear()
    _history[chat_id].append({"role": role, "content": text})


def _system_prompt(user_name: str | None) -> str:
    if user_name:
        return f"{AI_SYSTEM_PROMPT}\n\nТак пользователя зовут: {user_name}."
    return AI_SYSTEM_PROMPT


# ===== КАНАЛЫ =====
async def _post(url: str, payload: dict, headers: dict = None) -> str | None:
    """
    Один POST в OpenAI-совместимый API.
    Возвращает текст ответа модели либо None при любой проблеме.
    """
    host = url.split("/")[2]
    try:
        timeout = aiohttp.ClientTimeout(total=AI_TIMEOUT)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload, headers=headers or {}) as resp:
                if resp.status != 200:
                    body = (await resp.text())[:200].replace("\n", " ")
                    cl.log("LLM", "warning", f"{host} HTTP {resp.status}: {body}")
                    return None
                data = await resp.json()
        return ((data.get("choices") or [{}])[0].get("message") or {}).get("content")
    except NETWORK_ERRORS as exc:
        cl.log("LLM", "warning", f"{host}: сеть не ответила ({type(exc).__name__})")
        return None
    except Exception:
        cl.log("LLM", "error", traceback.format_exc())
        return None


async def _ask_deepseek(messages: list) -> str | None:
    """Первый канал: платный DeepSeek. Работает только с ключом."""
    if not (AI_ENABLED and deepseek_key):
        return None
    return await _post(DEEPSEEK_URL, {
        "model": deepseek_model,
        "messages": messages,
        "max_tokens": AI_MAX_TOKENS,
        "temperature": 0.8,
        "stream": False,
    }, {"Authorization": f"Bearer {deepseek_key}", "Content-Type": "application/json"})


async def _ask_pollinations(messages: list) -> str | None:
    """Второй канал: бесплатно и без ключа. Бережём лимит 1 запрос / 30 секунд."""
    global _poll_ok_at, _poll_blocked_until
    now = time.monotonic()
    if now < _poll_blocked_until:
        return None
    if _poll_ok_at and now - _poll_ok_at < POLL_FREE_GAP:
        return None
    try:
        reply = await _post(POLLINATIONS_URL, {
            "model": pollinations_model,
            "messages": messages,
            "max_tokens": min(AI_MAX_TOKENS, 800),
            "temperature": 0.8,
            "stream": False,
        }, {"Content-Type": "application/json"})
    except Exception:
        reply = None
    if reply:
        _poll_ok_at = now
    else:
        # Раз не получилось - не долбимся, иначе получим бан по IP
        _poll_blocked_until = now + POLL_FREE_GAP
    return reply


def _ask_brain(question: str, user_name: str | None, hard_only: bool = False) -> str | None:
    """
    Третий канал: собственный движок. Мгновенно, без сети и лимитов.
    Исключения гасим здесь - это последняя линия обороны, она не имеет права
    ронять обработчик сообщения.
    """
    try:
        return brain.answer(question, user_name=user_name, hard_only=hard_only)
    except Exception:
        cl.log("Brain", "error", traceback.format_exc()[-300:])
        return None


# ===== ПОГОДА В ЧАТЕ =====
# Погоду бот и так приносит каждое утро, поэтому вопрос «а какая погода?»
# в чате обязан получать тот же свежий ответ, а не «не знаю» из-за того, что
# бесплатный канал сейчас на паузе. Отвечаем данными Open-Meteo: они точнее,
# чем то, что выдумает модель без доступа в интернет.
# Список намеренно узкий: «дождь», «снег», «ветер» легко встречаются в
# романтических сообщениях («за окном дождь, а я скучаю»), и отвечать на них
# сводкой погоды - значит снова отвечать мимо. Реальный запрос погоды почти
# всегда содержит одно из этих слов.
_WEATHER_WORDS = ("погод", "температур", "прогноз", "градус", "зонт",
                  "как там на улице")
WEATHER_CACHE_SECONDS = 10 * 60
_weather_cache = {"at": 0.0, "text": None}


def _wants_weather(norm_source: str) -> bool:
    low = norm_source.lower()
    return any(word in low for word in _WEATHER_WORDS)


async def _ask_weather() -> str | None:
    """Свежая погода по данным Open-Meteo, с коротким кешем, чтобы не долбить API."""
    if not WEATHER_ENABLED:
        return None
    now = time.monotonic()
    if _weather_cache["text"] and now - _weather_cache["at"] < WEATHER_CACHE_SECONDS:
        return _weather_cache["text"]
    try:
        text = await weather.weather_text()
    except Exception:
        cl.log("Weather", "error", traceback.format_exc()[-300:])
        return None
    if text:
        _weather_cache.update(at=now, text=text)
    return text


def channels_status() -> str:
    """Человеческая строка про каналы - для /status в админ-панели."""
    deep = f"DeepSeek вкл ({deepseek_model})" if (AI_ENABLED and deepseek_key) else "DeepSeek: нет ключа"
    cooling = time.monotonic() < _poll_blocked_until or (
        _poll_ok_at and time.monotonic() - _poll_ok_at < POLL_FREE_GAP)
    poll = "на паузе до лимита" if cooling else "готов"
    sky = "погода в чате: готова" if WEATHER_ENABLED else "погода в чате: выкл"
    return f"{deep} | Pollinations без ключа: {poll} | свой мозг: готов | {sky} | последний: {last_source}"


# ===== ГЛАВНАЯ ТОЧКА ВХОДА =====
async def answer(chat_id, text: str, user_name: str = None) -> str | None:
    """
    Возвращает готовый к отправке текст ответа на сообщение пользователя,
    либо None - тогда caller обязан ответить чем-то своим (комплиментом).
    """
    global last_source
    text = (text or "").strip()
    if not text:
        return None

    question = text[:MAX_INPUT_CHARS]
    now = time.monotonic()

    # Погоду спрашиваем раньше всего остального и до антифлуда: ответ лежит в
    # кеше, сети он почти не касается, а иначе быстрая ветка ниже вернула бы
    # «не знаю» на вопрос, на который у нас есть точный свежий прогноз.
    if _wants_weather(question):
        sky = await _ask_weather()
        if sky:
            _remember(chat_id, "user", question)
            _remember(chat_id, "assistant", "свежий прогноз погоды отправлен")
            last_source = "Open-Meteo (вопрос про погоду)"
            # Разметку сводки собираем сами - экранировать её нельзя, иначе
            # пользователь увидел бы <b> прямо в сообщении
            return sky

    # Пока внешний канал занят нашим же прошлым запросом, отвечаем своими
    # силами: это мгновенно и не создаёт очередь из сетевых обращений.
    if chat_id in _busy or now - _last_call.get(chat_id, 0) < MIN_GAP_SECONDS:
        local = _ask_brain(question, user_name)
        if local:
            last_source = "свой мозг (канал был занят)"
            return to_telegram_html(local)
        return TEXT_BUSY

    _busy.add(chat_id)
    _last_call[chat_id] = now
    try:
        _remember(chat_id, "user", question)
        messages = [{"role": "system", "content": _system_prompt(user_name)}]
        messages.extend(_history[chat_id])

        # То, что собственный движок знает точно (арифметика, дата, гадание),
        # считаем сами, не дёргая сеть: быстрее и без расхода лимитов/токенов.
        hard = _ask_brain(question, user_name, hard_only=True)
        if hard:
            _remember(chat_id, "assistant", hard)
            last_source = "свой мозг"
            return to_telegram_html(hard)

        for name, sender in (("DeepSeek", lambda: _ask_deepseek(messages)),
                             ("Pollinations", lambda: _ask_pollinations(messages))):
            try:
                raw_reply = await sender()
            except Exception:
                # Отказ одного канала не должен лишать пользователя ответа:
                # пробуем следующий и в конце концов отвечаем собой.
                cl.log("LLM", "error", f"{name}: {traceback.format_exc()[-300:]}")
                continue
            reply = (raw_reply or "").strip()
            html_reply = to_telegram_html(reply) if reply else ""
            # Модель могла не ответить или вернуть только ```: наружу вышел бы
            # пустой <pre></pre>. Считаем это ответом без ответа.
            if html_reply and _visible(html_reply):
                _remember(chat_id, "assistant", reply)
                last_source = name
                return html_reply

        local = _ask_brain(question, user_name) or TEXT_UNKNOWN
        _remember(chat_id, "assistant", local)
        last_source = "свой мозг (внешние каналы молчали)"
        return to_telegram_html(local)
    finally:
        _busy.discard(chat_id)
