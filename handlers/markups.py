from aiogram import types

# def example_mkp():
#     btns = [
#         [
#             types.InlineKeyboardButton(text="Ряд 1, Кнопка 1", callback_data="callback_1_1"),
#             types.InlineKeyboardButton(text='Ряд 1, Кнопка 2', callback_data="callback_1_2")
#         ],
#         [
#             types.InlineKeyboardButton(text="Ряд 2, Кнопка 1", callback_data="callback_2_1"),
#             types.InlineKeyboardButton(text='Ряд 2, Кнопка 2', callback_data="callback_2_2")
#         ],
#     ]
#     return types.InlineKeyboardMarkup(inline_keyboard=btns)

def start_mkp():
    btns = [
        [
            types.InlineKeyboardButton(text="💋 Профиль", callback_data="profile")
        ],
        [
            types.InlineKeyboardButton(text="💕 О нас", callback_data="about")
        ],
        [
            types.InlineKeyboardButton(text="📖 Справка", callback_data="help")
        ],
        [
            types.InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings")
        ],
    ]
    return types.InlineKeyboardMarkup(inline_keyboard=btns)

def to_menu_mpk():
    btns = [
        [
            types.InlineKeyboardButton(text="Вернуться в меню", callback_data="start")
        ],
    ]
    return types.InlineKeyboardMarkup(inline_keyboard=btns)

def cancel_mpk():
    btns = [
        [types.InlineKeyboardButton(text="Отменить", callback_data="start")],
    ]
    return types.InlineKeyboardMarkup(inline_keyboard=btns)

def profile_mpk():
    btns = [
        [
            types.InlineKeyboardButton(text="💬 Связаться с разработчиками", callback_data="contact_with_devs")
        ],
        [
            types.InlineKeyboardButton(text="💋 Вернуться в меню", callback_data="start")
        ],
    ]
    return types.InlineKeyboardMarkup(inline_keyboard=btns)

def about_mkp():
    btns = [
        [
            types.InlineKeyboardButton(text="💖 Даша и Аднан", callback_data="about_us")
        ],
        [
            types.InlineKeyboardButton(text="💋 Вернуться в меню", callback_data="start")
        ],
    ]
    return types.InlineKeyboardMarkup(inline_keyboard=btns)

def story_mkp(page, total):
    btns = [[]]
    if page > 0:
        btns[0].append(types.InlineKeyboardButton(text="⬅️ Назад", callback_data=f"story_{page - 1}"))
    if page < total - 1:
        btns[0].append(types.InlineKeyboardButton(text="Дальше 💋", callback_data=f"story_{page + 1}"))
    if not btns[0]:
        btns.pop()
    btns.append([
        types.InlineKeyboardButton(text="💖 Даша и Аднан", callback_data="about_us")
    ])
    btns.append([
        types.InlineKeyboardButton(text="💋 Вернуться в меню", callback_data="start")
    ])
    return types.InlineKeyboardMarkup(inline_keyboard=btns)


def help_mkp():
    btns = [
        [types.InlineKeyboardButton(text="💋 Вернуться в меню", callback_data="start")],
    ]
    return types.InlineKeyboardMarkup(inline_keyboard=btns)


def settings_mkp():
    btns = [
        [types.InlineKeyboardButton(text="💋 Вернуться в меню", callback_data="start")],
    ]
    return types.InlineKeyboardMarkup(inline_keyboard=btns)