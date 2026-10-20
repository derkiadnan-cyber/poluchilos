import math
from aiogram import types
from db import User

def admin_mpk():
    btns = [
        [types.InlineKeyboardButton(text="Все юзеры", callback_data=f'all_users_1')],
        [types.InlineKeyboardButton(text="Рассылка", callback_data=f'admin_mailing')],
        [types.InlineKeyboardButton(text="Перезапуск бота", callback_data=f'restart_bot')],
    ]
    return types.InlineKeyboardMarkup(inline_keyboard=btns)

def back_to_admin_panel_mpk():
    btns = [
        [types.InlineKeyboardButton(text="Вернуться в админ-панель", callback_data=f'admin')],
    ]
    return types.InlineKeyboardMarkup(inline_keyboard=btns)

def all_users_admin_mpk(pageNum, usersCount, currentUsersList):
    btns = []
    currentDisplayed = pageNum * 5
    for user in currentUsersList:
        user: User
        btns.append([types.InlineKeyboardButton(text=f'{user.tg_id} - {user.fullname} (@{user.username})', callback_data=f'checkuser_{user.tg_id}_{pageNum}')])
    if pageNum != 1:
        if currentDisplayed < usersCount:
            btns.append([types.InlineKeyboardButton(text='⏪', callback_data=f'all_users_1'),
                         types.InlineKeyboardButton(text='◀️', callback_data=f'all_users_{pageNum - 1}'),
                         types.InlineKeyboardButton(text='▶️', callback_data=f'all_users_{pageNum + 1}'),
                         types.InlineKeyboardButton(text='⏩', callback_data=f'all_users_{math.ceil(usersCount/5)}')
                         ])
        else:
            btns.append([types.InlineKeyboardButton(text='⏪', callback_data=f'all_users_1'),
                         types.InlineKeyboardButton(text='◀️', callback_data=f'all_users_{pageNum - 1}'),
                         types.InlineKeyboardButton(text='▶️', callback_data=f'all_users_{pageNum}'),
                         types.InlineKeyboardButton(text='⏩', callback_data=f'all_users_{pageNum}')
                         ])
    else:
        if currentDisplayed < usersCount:
            btns.append([types.InlineKeyboardButton(text='⏪', callback_data=f'all_users_{pageNum}'),
                         types.InlineKeyboardButton(text='◀️', callback_data=f'all_users_{pageNum}'),
                         types.InlineKeyboardButton(text='▶️', callback_data=f'all_users_{pageNum + 1}'),
                         types.InlineKeyboardButton(text='⏩', callback_data=f'all_users_{math.ceil(usersCount/5)}')
                         ])
    btns.append([types.InlineKeyboardButton(text='Назад', callback_data=f'admin')])
    return types.InlineKeyboardMarkup(inline_keyboard=btns)

def user_admin_mpk(pageNum):
    btns = [
        [types.InlineKeyboardButton(text="Назад", callback_data=f'all_users_{pageNum}')],
    ]
    return types.InlineKeyboardMarkup(inline_keyboard=btns)