from aiogram import types

def mailing_mpk():
    btns = [
        [types.InlineKeyboardButton(text="Конкретного юзера", callback_data=f'admin_mailing_user')],
        [types.InlineKeyboardButton(text="Всех пользователей бота", callback_data=f'admin_mailing_all')],
        [types.InlineKeyboardButton(text="Отмена", callback_data=f'admin')],
    ]
    return types.InlineKeyboardMarkup(inline_keyboard=btns)

def mailing_cancel_mpk():
    btns = [
        [types.InlineKeyboardButton(text="Отмена", callback_data=f'admin_mailing')],
    ]
    return types.InlineKeyboardMarkup(inline_keyboard=btns)

def mailing_after_mpk():
    btns = [
        [types.InlineKeyboardButton(text="Вернуться в админ-панель", callback_data=f'admin')],
    ]
    return types.InlineKeyboardMarkup(inline_keyboard=btns)