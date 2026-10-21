from aiogram import types

from storage.config import dp, bot
import utils.custom_logger as cl


@dp.chat_join_request()
async def join_request(update: types.ChatJoinRequest):
    """
    Автоматически впускаем в канал и здороваемся.
    Здесь раньше ничего не было перехвачено: если пользователь уже был в канале
    или заблокировал бота, апдейт падал с необработанным исключением.
    """
    user = update.from_user
    if user is None:
        return
    try:
        await update.approve()
    except Exception as exc:
        # Обычно «user already a participant» - это не авария
        cl.log("ChatJoin", "info", f"approve не сработал: {type(exc).__name__}")

    try:
        await bot.send_message(user.id, "Спасибо за присоединение к каналу! 💋")
    except Exception:
        # Пользователь мог не запустить бота или заблокировать его - молча проходим
        pass