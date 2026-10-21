"""
Админ-панель: диагностика и управление.

Здесь всё, что нужно, чтобы не лазить в логи ради каждого пустяка:
  /testsend - прислать по одному сообщению каждого типа лично админу;
  /status   - самодиагностика: база, volume, получатели, каналы ответов, статистика;
  /admin    - панель со списком пользователей.
"""

import asyncio
import os
import time

from aiogram import types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from zoneinfo import ZoneInfo

from storage.config import dp, admins, TIMEZONE
from utils.scripts import safe_edit, safe_answer
from db import User

from .markups import *
from .states import tryFinish

# Точка отсчёта аптайма: модуль импортируется вместе с ботом
_STARTED_AT = time.monotonic()
TZ = ZoneInfo(TIMEZONE)


def _is_admin(user_id) -> bool:
    return user_id is not None and user_id in admins


def _pageNum(call, default=1) -> int:
    try:
        return max(1, int(call.data.split("_")[-1]))
    except (IndexError, ValueError):
        return default


def _local_time(dt) -> str:
    """
    Дата регистрации лежит в базе в UTC (так пишет SQLite в контейнере),
    поэтому показываем её в нашей таймзоне. Раньше сюда был вписан
    хардкод +3 часа, который врал летом и после смены таймзоны.
    """
    if not dt:
        return "неизвестно"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(TZ).strftime("%d/%m/%Y, %H:%M:%S")


async def _status_text() -> str:
    """Собирает картину мира бота в одно сообщение."""
    from storage.config import (db_path, DB_ON_VOLUME, IS_CLOUD, AUTOSEND,
                                giphy_token, unsplash_key, deepseek_key,
                                deepseek_model, AI_ENABLED, TIMEZONE,
                                SEND_GIF_MIN, SEND_POEM_MIN, SEND_CONFESSION_MIN,
                                SEND_PHOTO_MIN, MEME_MIN, MEME_ENABLED,
                                WEATHER_ENABLED, WEATHER_TIME, WEATHER_CITY,
                                MORNING_TIME, NIGHT_TIME)
    from managers.reminds import is_quiet_now, get_targets, stats
    from managers import ai, memes
    import utils.alerts as alerts

    uptime = int(time.monotonic() - _STARTED_AT)
    hours, rest = divmod(uptime, 3600)
    minutes, seconds = divmod(rest, 60)

    db_line = db_path if DB_ON_VOLUME else f"{db_path} ⚠️ сотрётся при деплое"
    lines = [
        "🔎 <b>Состояние бота</b>",
        f"  • аптайм: {hours}ч {minutes}м {seconds}с",
        f"  • окружение: {'облако (Railway)' if IS_CLOUD else 'локально'}",
        f"  • база: {db_line}",
        f"  • таймзона: {TIMEZONE}, сейчас {_local_time(__import__('datetime').datetime.now(ZoneInfo('UTC')))}",
        f"  • рассылки: {'вкл' if AUTOSEND else 'ВЫКЛ (AUTOSEND=off)'}",
        f"  • получателей: {len(get_targets())}",
        f"  • тихие часы сейчас: {'да' if is_quiet_now() else 'нет'}",
        f"  • интервалы: гифки {SEND_GIF_MIN}м, стихи {SEND_POEM_MIN}м, "
        f"признания {SEND_CONFESSION_MIN}м, фото {SEND_PHOTO_MIN}м"
        + (f", мемы {MEME_MIN}м" if MEME_ENABLED else ", мемы выкл"),
        f"  • утро {MORNING_TIME[0]:02d}:{MORNING_TIME[1]:02d}, "
        f"ночь {NIGHT_TIME[0]:02d}:{NIGHT_TIME[1]:02d}",
        f"  • гифки: {'Giphy поиск' if giphy_token else 'встроенный банк (без ключа)'}",
        f"  • фото: {'Unsplash по теме' if unsplash_key else 'встроенный банк (без ключа)'}",
        f"  • {memes.status_line()}",
        f"  • утренняя сводка: "
        + (f"{WEATHER_TIME[0]:02d}:{WEATHER_TIME[1]:02d} — погода ({WEATHER_CITY}) "
           f"и курс USD/BYN, источники без ключей"
           if WEATHER_ENABLED else "выключена (WEATHER_ENABLED=off)"),
        f"  • ответы на сообщения: {ai.channels_status()}",
        f"  • отправлено всего: {stats['sent']}, заблокировали: {stats['blocked']}, "
        f"битое медиа: {stats['media_error']}, прочего неудач: {stats['failed']}",
        f"  • тревог в очереди: {alerts.pending()}",
    ]
    if not (AI_ENABLED and deepseek_key):
        lines.append("  • 💡 ключ DeepSeek не задан — работают бесплатный Pollinations "
                     "и собственный движок")
    return "\n".join(lines)


@dp.message(Command("status"))
async def statusCmd(message: types.Message):
    """Самодиагностика: чем живёт бот прямо сейчас."""
    if not _is_admin(message.from_user.id if message.from_user else None):
        await message.answer("У тебя нет доступа к админ-панели")
        return
    await message.answer(await _status_text())


@dp.message(Command("testsend"))
async def testSendCmd(message: types.Message):
    """Прогоняет по одному сообщению каждого типа лично тебе, не дожидаясь интервалов."""
    if not _is_admin(message.from_user.id if message.from_user else None):
        await message.answer("У тебя нет доступа к админ-панели")
        return
    from managers.reminds import send_test

    await message.answer(await _status_text() + "\n\n📦 Прогоняю по одному сообщению каждого типа...")
    results = await send_test(message.from_user.id)
    await message.answer("📋 Результат:\n" + "\n".join(f"  • {r}" for r in results))


@dp.message(Command("admin"))
async def adminCmd(message: types.Message, state: FSMContext):
    if _is_admin(message.from_user.id if message.from_user else None):
        await tryFinish(state)
        allUsers = User.all()
        await message.answer(f"Админ-панель\n\nСтатистика:\nЮзеров - {len(allUsers)}",
                             reply_markup=admin_mpk())
    else:
        await message.answer("У тебя нет доступа к админ-панели")


@dp.callback_query(F.data == "admin")
async def adminCall(call: types.CallbackQuery, state: FSMContext):
    if not _is_admin(call.from_user.id if call.from_user else None):
        await safe_answer(call, "Нет доступа", True)
        return
    await tryFinish(state)
    allUsers = User.all()
    await safe_edit(call, f"Админ-панель\n\nСтатистика:\nЮзеров - {len(allUsers)}", admin_mpk())


@dp.callback_query(F.data.contains("all_users_"))
async def adminUsersMenuCall(call: types.CallbackQuery, state: FSMContext):
    if not _is_admin(call.from_user.id if call.from_user else None):
        await safe_answer(call, "Нет доступа", True)
        return
    pageNum = _pageNum(call)
    allUsers = User.all()
    pages = max(1, -(-len(allUsers) // 5))
    pageNum = min(pageNum, pages)
    currentUsersList = allUsers[((pageNum - 1) * 5):(pageNum * 5)]
    await safe_edit(
        call,
        f"Все юзеры (страница №{pageNum})\nЮзеров всего - {len(allUsers)}, "
        f"текущая страница - юзеры {((pageNum - 1) * 5) + 1} - {(pageNum * 5)}",
        all_users_admin_mpk(pageNum, len(allUsers), currentUsersList)
    )


@dp.callback_query(F.data.contains("checkuser_"))
async def adminUserMenuCall(call: types.CallbackQuery, state: FSMContext):
    if not _is_admin(call.from_user.id if call.from_user else None):
        await safe_answer(call, "Нет доступа", True)
        return
    parts = call.data.split("_")
    pageNum = _pageNum(call)
    # Кнопка могла протухнуть после рестарта: битые callback'ы не роняем
    try:
        tg_id = int(parts[1])
    except (IndexError, ValueError):
        await safe_answer(call, "Кнопка устарела, открой панель заново", True)
        return
    user = User.get(tg_id=tg_id)
    if user is None:
        await safe_answer(call, "Юзер не найден", True)
        return
    await safe_edit(
        call,
        f"Юзер {user.tg_id}\n{user.fullname} (@{user.username})\n"
        f"Дата регистрации - {_local_time(user.reg_datetime)}",
        user_admin_mpk(pageNum)
    )


@dp.callback_query(F.data == "restart_bot")
async def restartBotCall(call: types.CallbackQuery, state: FSMContext):
    """
    Перезапуск правильно делать через завершение процесса: Railway сам поднимет
    свежий контейнер. Раньше здесь вызывался dp.stop_polling(), после чего бот
    навсегда замолкал, а сервис продолжал висеть «живым» - перезапуска не было.
    """
    if not _is_admin(call.from_user.id if call.from_user else None):
        await safe_answer(call, "Нет доступа", True)
        return
    await tryFinish(state)
    await safe_answer(call, "Перезапускаю бота...")
    await call.message.answer("Перезапускаюсь, вернусь через минуту 💋")
    await asyncio.sleep(1)
    os._exit(0)
