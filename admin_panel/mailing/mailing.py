import asyncio

from aiogram.exceptions import TelegramRetryAfter
from aiogram.fsm.context import FSMContext
from aiogram import types, F

from storage.config import dp, bot, admins
from utils.scripts import safe_edit, safe_answer, safe_send
from db import User

from .markups import *
from .states import tryFinish, MailingAll, MailingUser

SEND_PAUSE = 0.1   # пауза между сообщениями, чтобы не словить лимит Telegram

# Проверка прав. Кнопки скрыты в админ-панели, но callback_data любой
# пользователь может подделать - поэтому права проверяем в самом хендлере,
# а не надеемся на скрытую клавиатуру.
def _is_admin(user_id) -> bool:
    return user_id is not None and user_id in admins


async def _deny(call: types.CallbackQuery):
    await safe_answer(call, "Нет доступа", True)


@dp.callback_query(F.data == "admin_mailing")
async def mailingCall(call: types.CallbackQuery, state: FSMContext):
    if not _is_admin(call.from_user.id if call.from_user else None):
        return await _deny(call)
    await tryFinish(state)
    await safe_edit(call, f'Раздел рассылок. Кого вы хотите уведомить?', mailing_mpk())


@dp.callback_query(F.data == "admin_mailing_all")
async def mailingAllCall(call: types.CallbackQuery, state: FSMContext):
    if not _is_admin(call.from_user.id if call.from_user else None):
        return await _deny(call)
    await safe_edit(call, f'Рассылка по всем юзерам. Введите сообщение', mailing_cancel_mpk())
    await state.set_state(MailingAll.Msg)


@dp.message(MailingAll.Msg)
async def mailingAllGoCall(message: types.Message, state: FSMContext):
    if not _is_admin(message.from_user.id if message.from_user else None):
        await message.answer("У тебя нет доступа к рассылкам")
        await tryFinish(state)
        return

    users = User.all()
    sent = skipped = 0
    await message.answer(f'Рассылка началась, получателей: {len(users)}')
    for user in users:
        user: User
        for attempt in (1, 2):
            try:
                await bot.copy_message(user.tg_id, message.from_user.id, message.message_id)
                sent += 1
                break
            except TelegramRetryAfter as e:
                # Telegram попросил притормозить - ждём и пробуем ещё раз,
                # иначе половина людей просто не получила бы сообщение
                if attempt == 1:
                    await asyncio.sleep(e.retry_after + 1)
                else:
                    skipped += 1
            except Exception:
                # Пользователь заблокировал бота - это не авария
                skipped += 1
                break
        await asyncio.sleep(SEND_PAUSE)

    await message.answer(f'Рассылка завершена: отправлено {sent}/{len(users)}, '
                         f'не дошло {skipped}', reply_markup=mailing_after_mpk())
    await tryFinish(state)


@dp.callback_query(F.data == "admin_mailing_user")
async def mailingUserCall(call: types.CallbackQuery, state: FSMContext):
    if not _is_admin(call.from_user.id if call.from_user else None):
        return await _deny(call)
    await safe_edit(call, f'Сообщение конкретному юзеру. Введите id юзера', mailing_cancel_mpk())
    await state.set_state(MailingUser.Id)

@dp.message(MailingUser.Id)
async def mailingUserIdCall(message: types.Message, state: FSMContext):
    if not _is_admin(message.from_user.id if message.from_user else None):
        await message.answer("У тебя нет доступа к рассылкам")
        await tryFinish(state)
        return
    try:
        tg_id = int(message.text)
    except (ValueError, TypeError):
        await message.answer(f"❌ Введите числовой id юзера", reply_markup=mailing_cancel_mpk())
        return
    await state.update_data(tg_id=tg_id)
    await message.answer(f'Юзер {tg_id}\n\nВведите текст:', reply_markup=mailing_cancel_mpk())
    await state.set_state(MailingUser.Msg)


@dp.message(MailingUser.Msg)
async def mailingUserGoCall(message: types.Message, state: FSMContext):
    if not _is_admin(message.from_user.id if message.from_user else None):
        await message.answer("У тебя нет доступа к рассылкам")
        await tryFinish(state)
        return
    # Данные могли потеряться (например, бот перезапустился посреди ввода)
    user_id = (await state.get_data()).get("tg_id")
    if not user_id:
        await message.answer("Сессия сбросилась, начните заново",
                             reply_markup=mailing_cancel_mpk())
        await tryFinish(state)
        return
    try:
        await bot.copy_message(user_id, message.from_user.id, message.message_id)
        await message.answer(f'Сообщение отправлено', reply_markup=mailing_after_mpk())
    except Exception as exc:
        # Полный traceback в чат не нужен, достаточно понятной причины
        await message.answer(f'Сообщение не отправлено: {type(exc).__name__}',
                             reply_markup=mailing_after_mpk())
    await tryFinish(state)