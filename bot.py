import asyncio

from storage.config import dp, bot
from managers.reminds import remindsManager
import utils.custom_logger as cl

import admin_panel.admin.admin
import admin_panel.mailing.mailing

import handlers.start
import handlers.profile
import handlers.chat_join
from db.models import dbSession


async def bot_stopped():
    cl.log("Bot", "critical", f"Bot has been stopped")

async def bot_started():
    cl.log("Bot", "warning", f"Bot has been started")

async def main():
    # Создание таблиц БД при старте
    await dbSession.create_all()

    # Фоновая задача для авто-рассылок
    asyncio.create_task(remindsManager())

    # Регистрация хуков
    dp.shutdown.register(bot_stopped)
    dp.startup.register(bot_started)

    # Основной цикл опроса
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())