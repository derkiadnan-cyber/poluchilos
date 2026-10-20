from aiogram.utils.deep_linking import decode_payload
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.utils.chat_action import ChatActionSender
from aiogram import types, F

from handlers.markups import *
import utils.custom_logger as cl
from utils.scripts import get_refer_id
from storage.config import dp, bot
from storage.states import tryFinish, State
from db import User


LOVE_STORY = [
    (
        '📱 <b>Глава 1. «Привет» от смелой девушки</b>\n\n'
        'Всё началось как в кино — с одной-единственной строчки в директ Instagram.\n\n'
        'Даша, не долго думая, написала Аднану первой: <i>«Привет 😏»</i>\n\n'
        'Сердце колотилось. Палец над кнопкой отправки. Момент — и сообщение ушло.\n\n'
        'А он... прочитал. И промолчал. 🍌',
    ),
    (
        '⏳ <b>Глава 2. Неприступный банан</b>\n\n'
        'Аднан включил режим «холодного парня».\n\n'
        'Прочитано — без ответа. Лайк на сторис — но ни слова в ответ.\n'
        'Даша писала снова и снова, а он держал оборону.\n\n'
        'Но правда в том, что каждое её сообщение он перечитывал по десять раз\n'
        'и улыбался телефону как дурак. 🫠\n\n'
        'Он динамил. Но уже проиграл.',
    ),
    (
        '🔥 <b>Глава 3. Банан растаял</b>\n\n'
        'В 3:47 ночи Аднан не выдержал и написал первым.\n\n'
        'Длинно. Неловко. Честно. С извинениями за молчание и с признанием,\n'
        'что она не идёт у него из головы.\n\n'
        'Даша ответила мгновенно — оказывается, она ждала.\n'
        'Их переписка в тот день умерла только к утру. ☀️',
    ),
    (
        '💋 <b>Глава 4. Вживую опаснее</b>\n\n'
        'Первая встреча была почти случайной — и почти катастрофой.\n\n'
        'Он нервничал. Она делала вид, что не нервничает.\n\n'
        'Первый взгляд вживую — и стало ясно: переписка была только разминкой. 😏\n\n'
        'Он проводил её домой. Долго не уходил.\n'
        'И в тот вечер они оба поняли — назад дороги нет.',
    ),
    (
        '🤫 <b>Глава 5. Тайный роман</b>\n\n'
        'Они решили: никто не должен знать.\n\n'
        'Никаких совместных фото, никаких лайков, никаких «мы вместе».\n\n'
        'Секретные свидания, шифровки в сообщениях, голосовые, записанные шёпотом в подушку. 😈\n\n'
        'Днём — незнакомцы. Ночью — самые близкие люди на планете.\n\n'
        'Их тайна была слаще любого поцелуя. 🍓',
    ),
    (
        '⚡ <b>Глава 6. Буря</b>\n\n'
        'Но у любой красивой истории бывает шторм.\n\n'
        'Ревность, недопонимание, одно глупое молчание длиной в несколько дней.\n\n'
        'Один раз они чуть не потеряли друг друга.\n\n'
        'Именно тогда Аднан понял: гордость не греет ночью, а «прости» — это не слабость. 🥀',
    ),
    (
        '💖 <b>Глава 7. Всё хорошо</b>\n\n'
        'Они вышли из бури держась за руки.\n\n'
        'Теперь весь мир знает: <b>Даша и Аднан — вместе</b>.\n\n'
        'Она всё ещё пишет ему первым. А он всё ещё отвечает... но уже через минуту. 😏🍌\n\n'
        '🌹 <i>«Лучшее решение в жизни — нажать "Отправить" в том директе»</i> 💋\n\n'
        '🍌💋 <b>Дашулик-Припевулик ❤️ любит Аднунку-Бананку навсегда</b> 💋🍌',
    ),
]


@dp.message(CommandStart())
async def startcmd(message: types.Message, command: CommandObject):
    async with ChatActionSender.typing(bot=bot, chat_id=message.from_user.id):
        referal_inviter_tg_id = get_refer_id(command.args)
        cl.log("Start Handler", "info", f"Registation (ref - {referal_inviter_tg_id})", message.from_user.id)
        fullname = f"{message.from_user.first_name}{' ' + message.from_user.last_name if message.from_user.last_name else ''}"
        username = f"{message.from_user.username}"
        User.get_or_create(message.from_user.id, fullname=fullname, username=username,
                        inviter_id=referal_inviter_tg_id if referal_inviter_tg_id else 0)
    await message.answer('💋 Любимки в деле? 💋', reply_markup=start_mkp())

@dp.callback_query(F.data == "start")
async def startCall(call: types.CallbackQuery, state: FSMContext):
    await tryFinish(state)
    await call.message.edit_text('💋 Любимки в деле? 💋', reply_markup=start_mkp())

@dp.callback_query(F.data == "about")
async def aboutCall(call: types.CallbackQuery, state: FSMContext):
    await tryFinish(state)
    await call.message.edit_text(
        LOVE_STORY[0][0],
        reply_markup=story_mkp(0, len(LOVE_STORY))
    )

@dp.callback_query(F.data.startswith("story_"))
async def storyPageCall(call: types.CallbackQuery, state: FSMContext):
    await tryFinish(state)
    page = int(call.data.split("_")[1])
    await call.message.edit_text(
        LOVE_STORY[page][0],
        reply_markup=story_mkp(page, len(LOVE_STORY))
    )
    await call.answer()

@dp.callback_query(F.data == "about_us")
async def aboutUsCall(call: types.CallbackQuery, state: FSMContext):
    await tryFinish(state)
    await call.message.edit_text(
        '🍌 <b>Аднунка-Бананка</b> 💋\n'
        '🎵 <b>Дашулик-Припевулик</b> 💋\n\n'
        '💕 <i>Два сердечка, одна мелодия</i> 💕\n\n'
        '🌹 <i>«Ты — мой любимый банан, а я твой припев — вместе мы песня!»</i> 🌹\n\n'
        '💖 Обнимаю виртуально, целую нежно 💖',
        reply_markup=to_menu_mpk()
    )