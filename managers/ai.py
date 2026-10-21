"""
Ответы на обычные сообщения пользователя через DeepSeek API.

DeepSeek отдаёт OpenAI-совместимый эндпоинт (https://api.deepseek.com/chat/completions),
поэтому никакие SDK не нужны - хватает aiohttp, который уже в зависимостях.

Ключ DEEPSEEK_API_KEY берётся из окружения (локально storage/.env, в облаке
Railway -> Variables). Ключей в репозитории нет и быть не должно.

Бот не должен молчать ни при каких условиях, поэтому у каждого сбоя есть
подстраховка: нет ключа / нет сети / модель вернула мусор - caller получает None
и отвечает комплиментом (см. handlers/fallbacks.py).
"""

import html as html_lib
import re
import time
import traceback
from collections import defaultdict, deque

import aiohttp

from managers.content import AI_SYSTEM_PROMPT
from storage.config import AI_ENABLED, AI_MAX_TOKENS, AI_TIMEOUT, deepseek_key, deepseek_model
import utils.custom_logger as cl

# OpenAI-совместимый адрес DeepSeek. Меняется только в тестах.
API_URL = "https://api.deepseek.com/chat/completions"

HISTORY_SIZE = 10          # реплик на один чат (user + assistant), ~5 вопросов
MAX_INPUT_CHARS = 2000     # длинные сообщения режем: лишние токены нам не нужны
MAX_ANSWER_CHARS = 3500    # лимит Telegram 4096, берём с запасом
MIN_GAP_SECONDS = 1.5      # антифлуд: не чаще одного запроса в секунду на чат
MAX_CHATS_IN_MEMORY = 500  # чтобы память контейнера не росла бесконечно

TEXT_BUSY = "Уже думаю над твоим прошлым сообщением 💋 Секунду, я рядом"

# История диалога, чтобы бот помел контекст переписки.
# Хранится в памяти процесса: после рестарта контейнера начинается с чистого листа,
# на рассылки и меню это не влияет.
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
    return _safe_truncate(_BLANK.sub("\n\n", text))


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


async def _ask_api(messages: list) -> str | None:
    """Один запрос к DeepSeek. Возвращает текст ответа или None при любой проблеме."""
    payload = {
        "model": deepseek_model,
        "messages": messages,
        "max_tokens": AI_MAX_TOKENS,
        "temperature": 0.8,
        "stream": False,
    }
    headers = {"Authorization": f"Bearer {deepseek_key}", "Content-Type": "application/json"}
    try:
        timeout = aiohttp.ClientTimeout(total=AI_TIMEOUT)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(API_URL, json=payload, headers=headers) as resp:
                if resp.status != 200:
                    body = (await resp.text())[:300]
                    cl.log("DeepSeek", "error", f"HTTP {resp.status}: {body}")
                    return None
                data = await resp.json()
        return ((data.get("choices") or [{}])[0].get("message") or {}).get("content")
    except Exception:
        cl.log("DeepSeek", "error", traceback.format_exc())
        return None


async def answer(chat_id, text: str, user_name: str = None) -> str | None:
    """
    Возвращает готовый к отправке текст ответа на сообщение пользователя,
    либо None - тогда caller обязан ответить чем-то своим (комплиментом).
    """
    text = (text or "").strip()
    if not text:
        return None
    if not AI_ENABLED or not deepseek_key:
        return None

    now = time.monotonic()
    if chat_id in _busy or now - _last_call.get(chat_id, 0) < MIN_GAP_SECONDS:
        return TEXT_BUSY
    _busy.add(chat_id)
    _last_call[chat_id] = now

    try:
        question = text[:MAX_INPUT_CHARS]
        _remember(chat_id, "user", question)
        messages = [{"role": "system", "content": _system_prompt(user_name)}]
        messages.extend(_history[chat_id])

        reply = (await _ask_api(messages) or "").strip()
        # Модель могла не ответить или вернуть только ```: наружу вышел бы пустой
        # <pre></pre>, а такое Telegram показывает пустой карточкой. Считаем это
        # ответом без ответа: убираем вопрос из истории (чтобы не тянуть его в
        # следующий запрос) и отдаём управление caller'у - он ответит комплиментом.
        reply_html = to_telegram_html(reply)
        if not reply_html or not _visible(reply_html):
            _history[chat_id].pop()
            return None

        _remember(chat_id, "assistant", reply)
        return reply_html
    finally:
        _busy.discard(chat_id)
