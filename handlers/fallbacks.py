"""
Запасные обработчики.
ВАЖНО: aiogram перебирает хендлеры в порядке их регистрации, поэтому этот
модуль должен импортироваться в bot.py ПОСЛЕДНИМ из handlers/* - иначе он
перехватит все апдейты раньше остальных.
Без этих хендлеров Telegram просто крутит «часики» на кнопке, а бот делает
вид, что ничего не было.
"""

from aiogram import types

from handlers.markups import start_mkp
from handlers.start import MENU_TEXT
from utils.scripts import safe_answer
from storage.config import dp


@dp.callback_query()
async def unknownCallback(call: types.CallbackQuery):
    # Любая неизвестная/устаревшая кнопка больше не зависает
    await safe_answer(call, "Эта кнопка устарела. Открой меню заново 💋", True)


@dp.message()
async def unknownMessage(message: types.Message):
    # Команды, которых нет в боте, не должны молчать
    if isinstance(message.command, str):
        await message.answer(
            f"🤔 Команду <code>/{message.command}</code> не знаю.\n"
            f"Вот что я умею 👇",
            reply_markup=start_mkp()
        )
        return
    await message.answer(MENU_TEXT, reply_markup=start_mkp())
