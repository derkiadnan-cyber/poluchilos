import asyncio
from datetime import datetime
import random
import traceback

import requests

from db import User
from handlers.markups import *
import utils.custom_logger as cl
from storage.config import admins, bot, giphy_token, AUTOSEND

FLIRTS = [
    "💋 Сегодня ты особенно соблазнительна... 😏",
    "🍑 Ох, как же хочется тебя обнять... 💕",
    "🔥 Горячий поцелуй для самой красивой... 💋",
    "🌶️ Знаешь, ты делаешь меня горячее, чем перец чили... 😏",
    "💦 Ты — мой любимый допинг... 🍌",
    "🍓 Хочу угостить тебя чем-нибудь сладким... 🤤",
    "🔥 От тебя так и тянет в жару... Огонь! 💋",
    "💋 Подойди ближе, у меня для тебя секрет... 😈",
    "🍑 Эти штанишки тебе совсем не нужны... 🫦",
    "🌶️ Ты как острый соус — всё, что делаешь, незабываемо... 🔥",
    "💦 Твой смех — лучшее, что я слышал... Но голос ещё лучше... 🎵",
    "🍓 Когда ты рядом, даже воздух становится сладким... 🤤",
    "🔥 Я бы тебя съел живьём... 🍽️",
    "💋 Ложись поудобнее... у меня для тебя приятный сюрприз... 🎁",
    "🍑 Ты как банан — желтенькая, сладенькая и... ну ты поняла... 🍌",
]

COMPLIMENTS_FROM_ADNAN = [
    "🍌💋 Даша, ты — мой самый сладкий банан в этом мире! Обожаю тебя! ❤️",
    "🌹 Дашулик-Припевулик, ты делаешь каждый мой день особенным! 💖",
    "🎵 Ты — мой любимый припев, без тебя мелодия моей жизни не играет! 🎶",
    "🍑 Дашенька, твои глаза ярче тысячи солнц! Я не могу на тебя наглядеться! 🔥",
    "🌶️ Даша, ты как острый перчик — горячая, дерзкая и незабываемая! 😏🔥",
    "💕 Аднан без ума от Даши — это факт, как 2+2=4! 💋",
    "🍓 Дашулик, ты — моя любимая клубничка! Сладкая, красивая, соблазнительная! 🤤",
    "🎀 Ты — мой лучший комплимент, Даша! Неважно, что я говорю — ты лучше! 🌹",
    "🌙 Даже луна завидует твоей красоте, Дашенька! 💫",
    "💋 Аднан отправляет тебе миллион поцелуев! Не считай, их слишком много! 😘",
    "🦋 Даша, ты — мой самый красивый бабочка! Порхаешь в моём сердце! 💖",
    "🌶️🔥 Ты — мой острый соус, Дашенька! С тобой жизнь — праздник! 🍌",
    "🎵 Припевулик-Даша — ты звучишь как лучшая песня! Аднан хочет слушать тебя вечно! 🎶",
    "🍑🍑 Даша, ты — мой любимый фрукт! Банан, клубника, манго — всё это ты! 🍌",
    "💖 Аднан любит Дашу больше, чем кофе по утрам! А это очень много! ☕😏",
    "🌹💋 Ты — моё самое любимое произведение искусства, Дашенька! 🎨",
    "🔥 Даша, от твоей улыбки у Аднана закипает кровь! 🩸💕",
    "🍓 Ты — моя сладкая жизнь, Дашулик! С тобой каждый момент — наслаждение! 🤤",
    "💋 Аднан целует тебя в носик, потом в щёчку, потом... ну ты поняла! 😘",
    "🌶️ Даша, ты — моё любимое блюдо! Острое, горячее, незабываемое! 🍽️🔥",
    "🎀 Дашенька, ты — мой лучший дизайн! Каждая деталь — шедевр! 💖",
    "🍌💕 Аднан — банан, Даша — припев! Вместе вы — самая горячая пара! 🍑🔥",
    "🌹 Даша, ты — мой букет роз! Каждый лепесток — отдельная причина любить тебя! 🥀",
    "💋 Ты — мой любимый звук, мой любимый запах, моя любимая... ВСЯ! 😍",
    "🔥 Аднан горит от одной мысли о Даше! Огонь-девушка! 🍑🌶️",
    "🎵 Даша-Припевулик — ты звучишь как мой любимый трек! Аднан ставит на повтор! 🎶",
    "🍑💋 Ты — мой самый сладкий сон, Дашенька! Просыпаюсь и думаю о тебе! 🌙",
    "🌶️ Даша, ты — мой любимый перец! Жгёшь, палишь, покоряешь! 😏🔥",
    "💖 Аднан без Даши как без рук! Она — его сердце, душа, жизнь! 💋",
    "🍓 Дашулик, ты — моя любимая клубничка! Сладкая до слёз! 🤤💕",
]

GIF_INTERVAL_SECONDS = 3 * 60 * 60  # каждые 3 часа
COMPLIMENT_INTERVAL_SECONDS = 2 * 60 * 60  # каждые 2 часа

async def get_gif_url():
    """Возвращает ссылку на случайную романтическую гифку с Giphy, либо None."""
    if not giphy_token:
        return None
    try:
        response = requests.get(
            "https://api.giphy.com/v1/gifs/search",
            params={
                "api_key": giphy_token,
                "q": "romantic kiss love",
                "limit": 25,
                "rating": "pg-13",
            },
            timeout=10,
        )
        results = response.json().get("data", [])
        if results:
            return random.choice(results)["images"]["original"]["gif_url"]
    except Exception:
        cl.log("Reminds Manager", "error", traceback.format_exc())
    return None

async def send_love_gif():
    """Отправляет админам романтическую гифку с флиртующей подписью."""
    gif_url = await get_gif_url()
    caption = random.choice(FLIRTS)
    for admin_id in admins:
        try:
            if gif_url:
                await bot.send_animation(admin_id, gif_url, caption=caption)
            else:
                await bot.send_message(admin_id, f"{caption}\n\n💋 Твой личный ботик")
        except Exception:
            cl.log("Reminds Manager", "error", traceback.format_exc())

async def send_compliment_from_adnan():
    """Отправляет админам креативный комплимент от имени Аднана."""
    text = random.choice(COMPLIMENTS_FROM_ADNAN)
    for admin_id in admins:
        try:
            await bot.send_message(admin_id, text)
            cl.log("Compliments", "info", f"✅ Комплимент отправлен админу {admin_id}")
        except Exception:
            cl.log("Compliments", "error", traceback.format_exc())

async def remindsManager():
    last_gif_time = datetime.now()   # старт таймера: первая рассылка — через полный интервал
    last_compliment_time = datetime.now()
    if AUTOSEND:
        cl.log("Reminds Manager", "info", "🟢 Авто-рассылки ВКЛЮЧЕНЫ")
    else:
        cl.log("Reminds Manager", "info", "🔒 Авто-рассылки ОТКЛЮЧЕНЫ (запустятся в облаке)")
    while True:
        try:
            cl.log("Reminds Manager", "debug", f"### Remind manager new cycle | Current datetime - {datetime.now()} ###")

            now = datetime.now()

            # Гифки каждые 3 часа
            if AUTOSEND and (now - last_gif_time).total_seconds() >= GIF_INTERVAL_SECONDS:
                await send_love_gif()
                last_gif_time = now

            # Комплименты от Аднана каждые 2 часа
            if AUTOSEND and (now - last_compliment_time).total_seconds() >= COMPLIMENT_INTERVAL_SECONDS:
                await send_compliment_from_adnan()
                last_compliment_time = now

            await asyncio.sleep(30)
        except Exception as ex:
            cl.log("Reminds Manager", "error", traceback.format_exc())
            await asyncio.sleep(30)