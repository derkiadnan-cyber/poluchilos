import datetime

from aiogram.utils.deep_linking import create_start_link, decode_payload
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram import types, F

from handlers.markups import *
from storage.config import dp, bot, admins
from storage.states import tryFinish, State, ContactWithDevs
from db import User


@dp.callback_query(F.data == "profile")
async def profileCall(call: types.CallbackQuery, state: FSMContext):
    await tryFinish(state)
    link = await create_start_link(bot, str(call.from_user.id))
    await call.message.edit_text(
        f'💋 Привет, {call.from_user.first_name}!\n\n'
        f'🌹 <i>«Ты — мой любимый банан, а я твой припев»</i> 🌹\n\n'
        f'💕 Твоя реферальная ссылка (делись с любимым человеком!):\n'
        f'<code>{link}</code>',
        reply_markup=profile_mpk()
    )

@dp.callback_query(F.data == "contact_with_devs")
async def contactWithDevsCall(call: types.CallbackQuery, state: FSMContext):
    await call.message.edit_text('Отправьте сообщение, фото, видео, стикер, все, что угодно - я передам его разработчикам', reply_markup=cancel_mpk())
    await state.set_state(ContactWithDevs.Message)

@dp.message(ContactWithDevs.Message)
async def contactWithDevsGoCall(message: types.Message, state: FSMContext):
    for adminTgId in admins:
        try:
            await bot.send_message(adminTgId, f"Новое сообщение от юзера {message.from_user.id} (@{message.from_user.username} | {message.from_user.full_name}) в {datetime.datetime.now().strftime("%d/%m/%Y, %H:%M:%S")}")
            await bot.copy_message(adminTgId, message.from_user.id, message.message_id)
        except:
            pass
    await message.answer(f'Ваше сообщение отправлено', reply_markup=to_menu_mpk())
    await tryFinish(state)