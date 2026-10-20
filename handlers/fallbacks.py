"""
Запасные обработчики.
ВАЖНО: aiogram перебирает хендлеры в порядке их регистрации, поэтому этот
модуль должен импортироваться в bot.py ПОСЛЕДНИМ из handlers/* - иначе он
перехватит все апдейты раньше остальных.
Без этих хендлеров Telegram просто крутит «часики» на кнопке, а бот делает
вид, что ничего не было.
"""

from aiogram import types

from managers import content
from utils.scripts import safe_answer, get_command_name
from storage.config import dp


@dp.callback_query()
async def unknownCallback(call: types.CallbackQuery):
    # Любая неизвестная/устаревшая кнопка больше не зависает
    await safe_answer(call, "Эта кнопка устарела. Открой меню заново 💋", True)


@dp.message()
async def unknownMessage(message: types.Message):
    # Команды, которых нет в боте, не должны молчать.
    # ВАЖНО: сюда приходим на ЛЮБОЕ сообщение без обработчика. Клавиатуру
    # меню тут не показываем - иначе «Профиль/О нас/Справка/Настройки»
    # будет всплывать на каждое слово пользователя. Меню отдаём только
    # по /start, /menu и кнопке «Вернуться в меню».
    command = get_command_name(message)
    if command:
        await message.answer(
            f"🤔 Команду <code>/{command}</code> не знаю.\n"
            f"Напиши <code>/menu</code> - покажу меню 💋"
        )
        return
    await message.answer(
        f"{content.next_compliment()}\n\n"
        f"💋 Меню откроется по команде <code>/menu</code>"
    )
