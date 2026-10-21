"""
Запасные обработчики.
ВАЖНО: aiogram перебирает хендлеры в порядке их регистрации, поэтому этот
модуль должен импортироваться в bot.py ПОСЛЕДНИМ из handlers/* - иначе он
перехватит все апдейты раньше остальных.
Без этих хендлеров Telegram просто крутит «часики» на кнопке, а бот делает
вид, что ничего не было.
"""

from aiogram import types
from aiogram.utils.chat_action import ChatActionSender

from managers import ai, content
from utils.scripts import safe_answer, get_command_name
from storage.config import bot, dp


@dp.callback_query()
async def unknownCallback(call: types.CallbackQuery):
    # Любая неизвестная/устаревшая кнопка больше не зависает
    await safe_answer(call, "Эта кнопка устарела. Открой меню заново 💋", True)


@dp.message()
async def unknownMessage(message: types.Message):
    # Всё, что не поймали остальные хендлеры.
    # ВАЖНО: клавиатуру меню тут не показываем - иначе «Профиль/О нас/Справка/
    # Настройки» всплывало бы на каждое слово пользователя. Меню отдаём только
    # по /start, /menu и кнопке «Вернуться в меню».
    command = get_command_name(message)
    if command:
        await message.answer(
            f"🤔 Команду <code>/{command}</code> не знаю.\n"
            f"Напиши <code>/menu</code> - покажу меню 💋"
        )
        return

    # Обычное сообщение: спрашиваем DeepSeek и отвечаем по существу.
    # Пока модель думает, показываем «печатает…», чтобы не вешать пользователя.
    if message.text:
        user_name = message.from_user.first_name if message.from_user else None
        async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
            reply = await ai.answer(message.chat.id, message.text, user_name=user_name)
        if reply:
            await message.answer(reply)
            return

    # Нет ключа, нет сети или модель вернула пустоту - отвечаем по-своему
    await message.answer(content.next_compliment())
