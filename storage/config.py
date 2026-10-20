import os

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
bot = Bot(bot_token, default=DefaultBotProperties(parse_mode='html'))
dp = Dispatcher()
router = Router()


botUrl = "t.me/"                             # url бота, например t.me/somebot
admins = [1191836733]                        # список ID админов (например - [123456, 7891011, 121314])

systemdServiceName = "some_bot"              # имя сервиса systemd для перезапуска через админ панель, например some_bot

DEBUG_MODE = False                          # Режим отладки (True/False), при True - в логах будет больше информации для отладки

# Авто рассылки (гифки + комплименты). Включается только когда AUTOSEND=on
# В облаке (Railway) добавь переменную окружения AUTOSEND=on — локально рассылки молчат
AUTOSEND = get_value_from_env_or("AUTOSEND", "off").lower() in ("1", "true", "on", "yes")