from dataclasses import dataclass
from environs import Env
from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties

def get_value_from_env(variable) -> str:
    env = Env()
    env.read_env("storage/.env")
    return env(variable)

def get_value_from_env_or(variable, default: str = "") -> str:
    env = Env()
    env.read_env("storage/.env")
    try:
        return env(variable) or default
    except Exception:
        return default

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