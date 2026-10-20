import json
from yookassa import Configuration, Payment
from storage.config import botUrl, get_value_from_env

YOOKASSA_SHOP_ID = int(get_value_from_env("YOOKASSA_SHOP_ID"))  # id магазина Юкассы
YOOKASSA_SECRET_TOKEN = get_value_from_env("YOOKASSA_SECRET_TOKEN")  # секретный токен Юкассы

class YOOKassa:
    Configuration.account_id = YOOKASSA_SHOP_ID
    Configuration.secret_key = YOOKASSA_SECRET_TOKEN

    def create_payment(value: int, description: str):
        payment = Payment.create({
        "amount": {
            "value": value,
            "currency": "RUB"
        },
        "confirmation": {
            "type": "redirect",
            "return_url": botUrl
        },
        "capture": True,
        "description": description,
        })

        return json.loads(payment.json())


    async def check_payment(payment_id: str):
        payment = json.loads((Payment.find_one(payment_id)).json())
        return payment['status']