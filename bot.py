import asyncio

from aiogram.types import BotCommand

from storage.config import (
    dp, bot, db_path, DB_ON_VOLUME, IS_CLOUD, AUTOSEND,
    giphy_token, unsplash_key,
)
from managers.reminds import remindsManager
import utils.custom_logger as cl

import admin_panel.admin.admin
import admin_panel.mailing.mailing

import handlers.start
import handlers.profile
import handlers.chat_join
import handlers.fallbacks
from db.models import dbSession


async def bot_stopped():
    cl.log("Bot", "critical", f"Bot has been stopped")

async def bot_started():
    cl.log("Bot", "info", f"Bot has been started | окружение: "
                          f"{'облако (Railway)' if IS_CLOUD else 'локально'}")

    # База на volume переживёт перезадеплой, база в контейнере - нет
    if DB_ON_VOLUME:
        cl.log("Bot", "info", f"База на volume: {db_path}")
    elif IS_CLOUD:
        cl.log("Bot", "warning",
               f"База {db_path} внутри контейнера - при следующем деплое юзеры сотрутся! "
               f"Прикрепи volume к сервису (путь /data), переменные не нужны - "
               f"путь подхватится сам")
    else:
        cl.log("Bot", "info", f"База: {db_path}")

    # Статус рассылок и источников медиа - чтобы не гадать, почему молчит
    if AUTOSEND:
        cl.log("Bot", "info",
               "Рассылки: вкл | "
               f"гифки: {'Giphy поиск' if giphy_token else 'встроенный банк (ключ не нужен)'} | "
               f"фото: {'Unsplash по теме' if unsplash_key else 'picsum (без ключа, не по теме)'}")
    else:
        cl.log("Bot", "info", "Рассылки: ВЫКЛ (AUTOSEND=off)")

    # Меню команд в Telegram должно совпадать с тем, что реально умеет бот
    await bot.set_my_commands([
        BotCommand(command="start", description="Запустить бота"),
        BotCommand(command="menu", description="Главное меню"),
        BotCommand(command="help", description="Помощь и справка"),
        BotCommand(command="settings", description="Настройки"),
    ])

async def main():
    # Создание таблиц БД при старте
    dbSession.create_all()

    # Фоновая задача для авто-рассылок
    asyncio.create_task(remindsManager())

    # Регистрация хуков
    dp.shutdown.register(bot_stopped)
    dp.startup.register(bot_started)

    # Основной цикл опроса
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())