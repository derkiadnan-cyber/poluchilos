from aiogram.utils.deep_linking import decode_payload
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.utils.chat_action import ChatActionSender
from aiogram import types, F

from handlers.markups import *
import utils.custom_logger as cl
from utils.scripts import get_refer_id, safe_edit, safe_answer
from storage.config import dp, bot, MEME_MIN, WEATHER_TIME, WEATHER_CITY
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


MENU_TEXT = '💋 Любимки в деле? 💋'

HELP_TEXT = (
    '📖 <b>Справка</b>\n\n'
    '💋 <b>Профиль</b> — твоя карточка и реферальная ссылка\n'
    '💕 <b>О нас</b> — история любви Даши и Аднана\n'
    '📖 <b>Справка</b> — этот экран\n'
    '⚙️ <b>Настройки</b> — управление ботом\n\n'
    '💬 <b>Просто напиши вопрос</b> — отвечу на что угодно: учёба, работа, '
    'код, перевод, рецепт или просто поболтать\n'
    '   например: <code>25*4</code>, <code>который час</code>, <code>напиши стих</code>\n'
    '   <i>никакой отсебятины вместо ответа — отвечаю по делу, но нежно 💋</i>\n\n'
    f'😂 <b>Мемы</b> — каждые {MEME_MIN} минут приношу самое смешное, русское\n'
    f'🌤 <b>Утро в {WEATHER_TIME[0]:02d}:{WEATHER_TIME[1]:02d}</b> — погода '
    f'({WEATHER_CITY}) на весь день и курс доллара к белорусскому рублю\n'
    '💌 <b>Рассылки</b> — фото, гифки, стихи про Дашу, признания, «доброе утро» '
    'и «спокойной ночи»\n\n'
    '🍌 Команды: <code>/start</code>, <code>/menu</code>, <code>/help</code>, <code>/settings</code>\n\n'
    '💖 <i>Меню показывается по <code>/menu</code> — на обычные сообщения я отвечаю текстом'
    '</i>'
)

SETTINGS_TEXT = (
    '⚙️ <b>Настройки</b>\n\n'
    'Здесь скоро появятся: тишина ночи 🌙, выбор комплиментов 💋 и напоминания ⏰\n\n'
    '💋 А пока можешь открыть свой профиль и забрать реферальную ссылку!'
)


@dp.message(CommandStart())
async def startcmd(message: types.Message, command: CommandObject):
    async with ChatActionSender.typing(bot=bot, chat_id=message.from_user.id):
        referal_inviter_tg_id = get_refer_id(command.args)
        cl.log("Start Handler", "info", f"Registation (ref - {referal_inviter_tg_id})", message.from_user.id)
        fullname = f"{message.from_user.first_name}{' ' + message.from_user.last_name if message.from_user.last_name else ''}"
        username = f"{message.from_user.username}"
        User.get_or_create(message.from_user.id, fullname=fullname, username=username,
                        inviter_id=referal_inviter_tg_id if referal_inviter_tg_id else 0)
    await message.answer(MENU_TEXT, reply_markup=start_mkp())

@dp.message(Command("menu"))
async def menuCmd(message: types.Message):
    await message.answer(MENU_TEXT, reply_markup=start_mkp())

@dp.message(Command("help"))
async def helpCmd(message: types.Message):
    await message.answer(HELP_TEXT, reply_markup=help_mkp())

@dp.message(Command("settings"))
async def settingsCmd(message: types.Message):
    await message.answer(SETTINGS_TEXT, reply_markup=settings_mkp())

@dp.callback_query(F.data == "start")
async def startCall(call: types.CallbackQuery, state: FSMContext):
    await tryFinish(state)
    await safe_edit(call, MENU_TEXT, start_mkp())

@dp.callback_query(F.data == "help")
async def helpCall(call: types.CallbackQuery, state: FSMContext):
    await tryFinish(state)
    await safe_edit(call, HELP_TEXT, help_mkp())

@dp.callback_query(F.data == "settings")
async def settingsCall(call: types.CallbackQuery, state: FSMContext):
    await tryFinish(state)
    await safe_edit(call, SETTINGS_TEXT, settings_mkp())

@dp.callback_query(F.data == "about")
async def aboutCall(call: types.CallbackQuery, state: FSMContext):
    await tryFinish(state)
    await safe_edit(call, LOVE_STORY[0][0], story_mkp(0, len(LOVE_STORY)))

@dp.callback_query(F.data.startswith("story_"))
async def storyPageCall(call: types.CallbackQuery, state: FSMContext):
    await tryFinish(state)
    try:
        page = int(call.data.split("_")[1])
    except (IndexError, ValueError):
        await safe_answer(call, "Страница не найдена", True)
        return
    if not 0 <= page < len(LOVE_STORY):
        await safe_answer(call, "Страница не найдена", True)
        return
    await safe_edit(call, LOVE_STORY[page][0], story_mkp(page, len(LOVE_STORY)))

@dp.callback_query(F.data == "about_us")
async def aboutUsCall(call: types.CallbackQuery, state: FSMContext):
    await tryFinish(state)
    await safe_edit(
        call,
        '🍌 <b>Аднунка-Бананка</b> 💋\n'
        '🎵 <b>Дашулик-Припевулик</b> 💋\n\n'
        '💕 <i>Два сердечка, одна мелодия</i> 💕\n\n'
        '🌹 <i>«Ты — мой любимый банан, а я твой припев — вместе мы песня!»</i> 🌹\n\n'
        '💖 Обнимаю виртуально, целую нежно 💖',
        to_menu_mpk()
    )