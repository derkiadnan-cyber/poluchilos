from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError


def get_refer_id(command_args):
    try:
        return int(command_args)
    except (TypeError, ValueError):
        return None


async def safe_edit(call, text, reply_markup=None):
    """
    Редактирует сообщение под кнопкой и всегда гасит «часики» у пользователя.
    Telegram отказывается редактировать сообщение, если содержимое не изменилось,
    из-за чего кнопка выглядела «нерабочей».
    """
    try:
        await call.message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as e:
        # Сообщение уже показывает этот же текст - ничего страшного
        if "message is not modified" not in str(e).lower():
            raise
    except TelegramForbiddenError:
        pass
    await safe_answer(call)


async def safe_answer(call, text=None, show_alert=False):
    """Подтверждает обработку callback_query (без этого Telegram крутит нагрузку)."""
    try:
        await call.answer(text, show_alert=show_alert)
    except Exception:
        # callback уже протух (дубль нажатия) - игнорируем
        pass


async def safe_send(chat_id, text, reply_markup=None, bot=None):
    """Отправка сообщения с защитой от заблокированного бота пользователя."""
    if bot is None:
        from storage.config import bot as config_bot
        bot = config_bot
    try:
        return await bot.send_message(chat_id, text, reply_markup=reply_markup)
    except (TelegramForbiddenError, TelegramBadRequest):
        return None