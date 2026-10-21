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

from managers import ai, reminds
from utils.scripts import safe_answer, get_command_name
from storage.config import bot, dp

# Прилетело фото/стикер/голосовое: картинки бот не распознаёт. Раньше сюда
# подставлялся случайный комплимент - выглядело мило, но по делу не отвечало
# ничего, а пользователь думал, что его не поняли из вредности.
NON_TEXT_HINT = ("Картинки и голос я пока не умею читать 🙈\n"
                 "Напиши словами, что там или о чём хочешь — отвечу по делу 💋")

# Просьба про мем. Картинку текстом не заменишь, поэтому такие сообщения
# идут мимо каскада: нашли мем - прислали, не нашли - ответим словами.
MEME_WORDS = ("мем", "мемы", "поржи")


def _wants_meme(text: str) -> bool:
    low = text.lower()
    return any(word in low for word in MEME_WORDS)


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

    # Обычное сообщение: каскад из managers/ai.py обязан ответить.
    # Пока каналы думают, показываем «печатает…», чтобы не вешать пользователя.
    # Подпись под фото/видео - тоже текст, отвечаем на неё как на сообщение.
    text = message.text or message.caption
    if text:
        user_name = message.from_user.first_name if message.from_user else None

        # «Мем» - не вопрос, а просьба показать картинку
        if _wants_meme(text) and await reminds.send_meme_to(message.chat.id):
            return

        async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
            reply = await ai.answer(message.chat.id, text, user_name=user_name)
        if reply:
            await message.answer(reply)
            return

    await message.answer(NON_TEXT_HINT)
