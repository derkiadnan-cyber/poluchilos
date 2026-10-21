"""
Точка входа. Здесь только запуск и надзор за фоном: бот должен чинить сам себя
то, что чинится автоматически, и честно сообщать о том, что сломалось.
"""

import asyncio
import traceback

from aiogram.types import BotCommand

from storage.config import (
    dp, bot, db_path, DB_ON_VOLUME, IS_CLOUD, AUTOSEND,
    giphy_token, unsplash_key, deepseek_key, deepseek_model, AI_ENABLED,
)
from managers.reminds import remindsManager
from managers import content
import utils.custom_logger as cl

import admin_panel.admin.admin
import admin_panel.mailing.mailing

import handlers.start
import handlers.profile
import handlers.chat_join
import handlers.fallbacks
from db.models import dbSession

# Задачи держим в переменных. asyncio хранит задачи по СЛАБЫМ ссылкам: если
# результат create_task() никуда не сохранить, сборщик мусора может убить
# задачу прямо посреди работы - и рассылки молча перестанут ходить.
_tasks = {}


async def _supervised(name: str, factory):
    """
    Бесконечно держит фоновую задачу живой: упала - перезапускаем с паузой,
    чтобы не крутить колесо на постоянной аварии.
    """
    restarts = 0
    while True:
        try:
            await factory()
            cl.log("Supervisor", "warning", f"задача {name} завершилась сама")
            return
        except asyncio.CancelledError:
            raise
        except Exception:
            restarts += 1
            wait = min(300, 10 * restarts)
            cl.log("Supervisor", "error",
                   f"задача {name} упала (#{restarts}), старт через {wait}с\n"
                   f"{traceback.format_exc()[-700:]}")
            await asyncio.sleep(wait)


def _spawn(name: str, factory) -> None:
    _tasks[name] = asyncio.create_task(_supervised(name, factory), name=name)


async def bot_stopped():
    """Аккуратно сворачиваемся: снимаем фон и закрываем сетевую сессию бота."""
    for name, task in _tasks.items():
        task.cancel()
    for task in _tasks.values():
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
    _tasks.clear()
    # Закрываем именно HTTP-сессию. bot.close() — это метод Telegram API
    # ("снять бота с сервера"), он тут не нужен и только мешает перезапуску.
    try:
        await bot.session.close()
    except Exception:
        pass
    cl.log("Bot", "critical", "Bot has been stopped")


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
               f"фото: {'Unsplash по теме' if unsplash_key else f'встроенный банк из {len(content.ROMANTIC_PHOTOS)} фото (ключ не нужен)'}")
    else:
        cl.log("Bot", "info", "Рассылки: ВЫКЛ (AUTOSEND=off)")

    # Ответы на сообщения пользователя: каскад DeepSeek -> Pollinations -> свой мозг
    if AI_ENABLED and deepseek_key:
        cl.log("Bot", "info", f"Ответы на сообщения: DeepSeek ({deepseek_model}) "
                              f"+ бесплатный резерв и свой движок")
    elif AI_ENABLED:
        cl.log("Bot", "info",
               "Ответы на сообщения: бесплатный Pollinations + свой движок. "
               "Для быстрого платного канала добавь DEEPSEEK_API_KEY")
    else:
        cl.log("Bot", "info", "Ответы на сообщения: только свой движок (AI_ENABLED=off)")

    # Меню команд в Telegram должно совпадать с тем, что реально умеет бот
    await bot.set_my_commands([
        BotCommand(command="start", description="Запустить бота"),
        BotCommand(command="menu", description="Главное меню"),
        BotCommand(command="help", description="Помощь и справка"),
        BotCommand(command="settings", description="Настройки"),
        BotCommand(command="status", description="Состояние бота (админам)"),
    ])

    # Селф-чек: сразу видно, если контент или конфиг сломаны, а не через час молчания
    try:
        from selfcheck import run_checks
        problems = run_checks(quiet=True)
        if problems:
            cl.log("SelfCheck", "error", "после старта найдены проблемы: "
                                         + "; ".join(problems))
        else:
            cl.log("SelfCheck", "info", "самопроверка пройдена")
    except Exception:
        cl.log("SelfCheck", "warning", f"не смог самопровериться:\n{traceback.format_exc()[-400:]}")


async def main():
    # Создание таблиц БД при старте
    dbSession.create_all()

    # Фоновые задачи под надзором: упала - поднимется сама
    _spawn("reminds", remindsManager)

    # Регистрация хуков
    dp.shutdown.register(bot_stopped)
    dp.startup.register(bot_started)

    # Основной цикл опроса
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        cl.log("Bot", "critical", "остановка по Ctrl+C")
