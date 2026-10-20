import datetime
from aiogram import types, F
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command

from storage.config import dp, admins
from utils.scripts import safe_edit, safe_answer
from db import User

from .markups import *
from .states import tryFinish


def _pageNum(call, default=1) -> int:
    try:
        return max(1, int(call.data.split("_")[-1]))
    except (IndexError, ValueError):
        return default


@dp.message(Command('testsend'))
async def testSendCmd(message: types.Message):
    """Прогоняет по одному сообщению каждого типа лично тебе, не дожидаясь интервалов."""
    if message.from_user.id not in admins:
        await message.answer("У тебя нет доступа к админ-панели")
        return
    from managers.reminds import send_test, is_quiet_now, get_targets
    progress = await message.answer(
        f"🔎 Прогоняю все типы рассылки по одному разу...\n"
        f"Юзеров в базе: {len(get_targets())}\n"
        f"Сейчас тихие часы: {'да' if is_quiet_now() else 'нет'}"
    )
    results = await send_test(message.from_user.id)
    await progress.answer(
        "📋 Результат проверки:\n" + "\n".join(f"  • {r}" for r in results)
    )

@dp.message(Command('admin'))
async def adminCmd(message: types.Message, state: FSMContext):
    if message.from_user.id in admins:
        await tryFinish(state)
        allUsers = User.all()
        await message.answer(f"Админ-панель\n\nСтатистика:\nЮзеров - {len(allUsers)}", reply_markup=admin_mpk())
    else:
        await message.answer("У тебя нет доступа к админ-панели")

@dp.callback_query(F.data == "admin")
async def adminCall(call: types.CallbackQuery, state: FSMContext):
    await tryFinish(state)
    allUsers = User.all()
    await safe_edit(call, f"Админ-панель\n\nСтатистика:\nЮзеров - {len(allUsers)}", admin_mpk())

@dp.callback_query(F.data.contains("all_users_"))
async def adminUsersMenuCall(call: types.CallbackQuery, state: FSMContext):
    pageNum = _pageNum(call)
    allUsers = User.all()
    pages = max(1, -(-len(allUsers) // 5))
    pageNum = min(pageNum, pages)
    currentUsersList = allUsers[((pageNum - 1) * 5):(pageNum * 5)]
    await safe_edit(
        call,
        f"Все юзеры (страница №{pageNum})\nЮзеров всего - {len(allUsers)}, текущая страница - юзеры {((pageNum - 1) * 5) + 1} - {(pageNum * 5)}",
        all_users_admin_mpk(pageNum, len(allUsers), currentUsersList)
    )

@dp.callback_query(F.data.contains("checkuser_"))
async def adminUserMenuCall(call: types.CallbackQuery, state: FSMContext):
    parts = call.data.split("_")
    pageNum = _pageNum(call)
    user = User.get(tg_id=int(parts[1]))
    if user is None:
        await safe_answer(call, "Юзер не найден", True)
        return
    regDatetime = user.reg_datetime
    regDatetime = (regDatetime + datetime.timedelta(hours=3)).strftime("%d/%m/%Y, %H:%M:%S") if regDatetime else "неизвестно"
    await safe_edit(
        call,
        f"Юзер {user.tg_id}\n{user.fullname} (@{user.username})\nДата регистрации - {regDatetime}",
        user_admin_mpk(pageNum)
    )

@dp.callback_query(F.data == "restart_bot")
async def restartBotCall(call: types.CallbackQuery, state: FSMContext):
    await tryFinish(state)
    await safe_answer(call, "Перезапускаю бота...")
    await call.message.answer("Перезапуск бота...")
    await dp.stop_polling()
