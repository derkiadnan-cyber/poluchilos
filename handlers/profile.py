import datetime
from zoneinfo import ZoneInfo

from aiogram.utils.deep_linking import create_start_link
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram import types, F

from handlers.markups import *
from utils.scripts import safe_edit, safe_answer
from storage.config import dp, bot, admins, TIMEZONE
from storage.states import tryFinish, State, ContactWithDevs
from db import User

TZ = ZoneInfo(TIMEZONE)


@dp.callback_query(F.data == "profile")
async def profileCall(call: types.CallbackQuery, state: FSMContext):
    await tryFinish(state)
    link = await create_start_link(bot, str(call.from_user.id))
    await safe_edit(
        call,
        f'💋 Привет, {call.from_user.first_name}!\n\n'
        f'🌹 <i>«Ты — мой любимый банан, а я твой припев»</i> 🌹\n\n'
        f'💕 Твоя реферальная ссылка (делись с любимым человеком!):\n'
        f'<code>{link}</code>',
        profile_mpk()
    )

@dp.callback_query(F.data == "contact_with_devs")
async def contactWithDevsCall(call: types.CallbackQuery, state: FSMContext):
    await safe_edit(call, 'Отправьте сообщение, фото, видео, стикер, все, что угодно - я передам его разработчикам', cancel_mpk())
    await state.set_state(ContactWithDevs.Message)

@dp.message(ContactWithDevs.Message)
async def contactWithDevsGoCall(message: types.Message, state: FSMContext):
    now = datetime.datetime.now(TZ).strftime("%d/%m/%Y, %H:%M:%S")
    user = message.from_user
    who = f"{user.id} (@{user.username} | {user.full_name})" if user else "неизвестный"
    for adminTgId in admins:
        try:
            await bot.send_message(adminTgId, f"Новое сообщение от юзера {who} в {now}")
            await bot.copy_message(adminTgId, message.from_user.id, message.message_id)
        except Exception:
            # Админ мог заблокировать бота - остальным всё равно должно дойти
            pass
    await message.answer(f'Ваше сообщение отправлено', reply_markup=to_menu_mpk())
    await tryFinish(state)