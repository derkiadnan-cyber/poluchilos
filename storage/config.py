import os
import re

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties

# Локально подхватываем storage/.env, если он есть.
# В облаке файла нет - тогда переменные берутся из окружения (Railway Variables).
load_dotenv("storage/.env")


def get_value_from_env(variable) -> str:
    value = os.getenv(variable)
    if not value:
        raise RuntimeError(
            f"Environment variable '{variable}' is not set. "
            f"Add it in Railway -> Service -> Variables"
        )
    return value


def get_value_from_env_or(variable, default: str = "") -> str:
    return os.getenv(variable) or default


bot_token = get_value_from_env("BOT_TOKEN")
giphy_token = get_value_from_env_or("GIPHY_TOKEN")
unsplash_key = get_value_from_env_or("UNSPLASH_ACCESS_KEY")
deepseek_key = get_value_from_env_or("DEEPSEEK_API_KEY")
bot = Bot(bot_token, default=DefaultBotProperties(parse_mode='html'))
dp = Dispatcher()
router = Router()


# ===== БАЗА ДАННЫХ =====
# Railway сам отдаёт путь примонтированного volume, если он прикреплён.
# Используем его автоматически: база ляжет на диск, который НЕ стирается
# при перезадеплое. Своя переменная DB_PATH всё ещё важнее.
_volume_mount = get_value_from_env_or("RAILWAY_VOLUME_MOUNT_PATH")
db_path = get_value_from_env_or(
    "DB_PATH",
    f"{_volume_mount.rstrip('/')}/db.db" if _volume_mount else "db.db",
)
# Volume не прикреплён - база будет жить в контейнере и сотрётся при следующем деплое
DB_ON_VOLUME = bool(_volume_mount) and db_path.startswith(_volume_mount.rstrip("/"))

botUrl = "t.me/"                             # url бота, например t.me/somebot
# Список админов берём из ADMIN_IDS в .env / переменных окружения (формат: 123,456 или [123, 456])
admins = [int(x) for x in re.findall(r"-?\d+", get_value_from_env_or("ADMIN_IDS", "1191836733"))]

systemdServiceName = "some_bot"              # имя сервиса systemd для перезапуска через админ панель, например some_bot

DEBUG_MODE = False                          # Режим отладки (True/False), при True - в логах будет больше информации для отладки

def _flag(variable, default: str = "on") -> bool:
    return get_value_from_env_or(variable, default).lower() in ("1", "true", "on", "yes")


def _minutes(variable, default: int) -> int:
    """Читает интервал в минутах, не падая на мусоре в переменной окружения."""
    raw = get_value_from_env_or(variable, str(default))
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def _number(variable, default: int, minimum: int = 1) -> int:
    """Читает целое число из окружения, не падая на мусоре."""
    raw = get_value_from_env_or(variable, str(default))
    try:
        return max(minimum, int(raw))
    except ValueError:
        return default


def _hhmm(variable, default: str) -> tuple:
    """Читает время вида ЧЧ:ММ и возвращает кортеж (часы, минуты)."""
    raw = get_value_from_env_or(variable, default)
    try:
        hh, mm = raw.strip().split(":")
        hh, mm = int(hh), int(mm)
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return hh, mm
    except ValueError:
        pass
    return tuple(int(x) for x in default.split(":"))


# ===== АВТО-РАССЫЛКИ =====
# Railway сам подставляет служебные переменные - по ним понимаем, где запущен бот.
# Локально их нет, в облаке они есть всегда.
IS_CLOUD = bool(get_value_from_env_or("RAILWAY_PROJECT_ID")
                or get_value_from_env_or("RAILWAY_SERVICE_ID"))

# Главный выключатель рассылок.
# В облаке включён по умолчанию, локально - выключен, чтобы тесты не спамили юзерам.
# Явная переменная окружения всегда важнее автоопределения (AUTOSEND=off выключит и в облаке).
AUTOSEND = _flag("AUTOSEND", "on" if IS_CLOUD else "off")

# Часовой пояс для утренних и ночных рассылок (Railway живёт в UTC, поэтому важно)
TIMEZONE = get_value_from_env_or("TIMEZONE", "Europe/Moscow")

# Интервалы периодических рассылок, в минутах
SEND_POEM_MIN = _minutes("SEND_POEM_MIN", 60)          # милые стишки про Дашу
SEND_CONFESSION_MIN = _minutes("SEND_CONFESSION_MIN", 120)  # любовные признания
SEND_PHOTO_MIN = _minutes("SEND_PHOTO_MIN", 180)       # любовные фото
SEND_GIF_MIN = _minutes("SEND_GIF_MIN", 30)            # гифки с обнимашками

# Фиксированные времена рассылки (в таймзоне TIMEZONE)
MORNING_TIME = _hhmm("MORNING_TIME", "08:00")          # доброе утро
NIGHT_TIME = _hhmm("NIGHT_TIME", "22:00")              # спокойной ночи

# Тихие часы: в это время периодические рассылки молчат,
# но «доброе утро» и «спокойной ночи» приходят как обычно.
QUIET_HOURS = _flag("QUIET_HOURS", "on")
QUIET_FROM = _hhmm("QUIET_FROM", "22:30")
QUIET_TO = _hhmm("QUIET_TO", "07:30")


# ===== ОТВЕТЫ НА СООБЩЕНИЯ ПОЛЬЗОВАТЕЛЯ =====
# Бот отвечает на любое обычное сообщение. Каскад каналов (см. managers/ai.py):
#   1. DeepSeek, если задан DEEPSEEK_API_KEY
#   2. Pollinations - бесплатно и без всяких ключей
#   3. Свой движок managers/brain.py - работает даже без интернета
# То есть бот отвечает всегда, а ключ DeepSeek только делает ответы быстрее.
AI_ENABLED = _flag("AI_ENABLED", "on")

# deepseek-flash - актуальная модель API (V4.1 Flash). Старые имена
# deepseek-chat / deepseek-reasoner DeepSeek отключил 24.07.2026.
deepseek_model = get_value_from_env_or("DEEPSEEK_MODEL", "deepseek-flash")

# Модель бесплатного Pollinations. Список доступных: text.pollinations.ai/models
pollinations_model = get_value_from_env_or("POLLINATIONS_MODEL", "openai")

# Сколько токенов разрешаем отдать модели: сообщения в Telegram короткие,
# переплачивать за простыни незачем
AI_MAX_TOKENS = _number("AI_MAX_TOKENS", 700, 100)

# Сколько секунд ждём ответ. DeepSeek отвечает быстрее этого, но сеть есть сеть
AI_TIMEOUT = _number("AI_TIMEOUT", 30, 5)