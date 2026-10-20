from aiogram import types
from db.models import Payments

def payment_mpk(pay_id):
    payment = Payments.get(id=pay_id)
    btns = [
        [types.InlineKeyboardButton(text="Оплатить", url=payment.link)],
        [types.InlineKeyboardButton(text="Проверить оплату", callback_data=f'paymentcheck_{pay_id}')],
        [types.InlineKeyboardButton(text="Вернуться в меню", callback_data=f'start')],
    ]
    return types.InlineKeyboardMarkup(inline_keyboard=btns)