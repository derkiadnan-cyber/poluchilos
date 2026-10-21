"""
Утренняя сводка: погода в Минске на весь день + курс доллара к белорусскому рублю.

Оба источника бесплатные и работают БЕЗ КЛЮЧЕЙ:

  * погода  - Open-Meteo (api.open-meteo.com). Открытый API без регистрации,
    ограничения только на очень агрессивные запросы. Берём текущую погоду,
    поминутно по часам и сводку дня в таймзоне города, поэтому «сегодня»,
    «восход» и «закат» считаются по Минску, а не по UTC контейнера Railway.
  * валюта  - официальный API Нацбанка Республики Беларусь (api.nbrb.by).
    Это именно официальный курс НБ РБ, а не сторонний агрегатор: цифры те же,
    что на nbrb.by. Код доллара в справочнике - 431.

Честно про точность: Open-Meteo - модельная погода (GFS/ICON и т.п.), она
может разойтись с фактом на градус-два, это нормально для прогноза. Если сеть
лежит или источник отдал ерунду, сводка просто не уходит - вместо выдуманной
погоды бот промолчит, а «доброе утро» придёт как обычно.

Текст собирается обычными символами без HTML-тегов: рассылка уходит с
parse_mode=HTML, и случайная угловая скобка отвергла бы всё сообщение.
"""

import asyncio
import html as html_lib
import re
import traceback
from datetime import datetime
from zoneinfo import ZoneInfo

import aiohttp

from db import BotState
from storage.config import (FX_USD_ID, WEATHER_CITY, WEATHER_LAT, WEATHER_LON,
                            WEATHER_TZ)
import utils.custom_logger as cl

WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
NBRB_RATE_URL = "https://api.nbrb.by/exrates/rates/{currency_id}"
USER_AGENT = "romance-bot/1.0 (personal telegram bot)"
HTTP_TIMEOUT = 20

# Ключ в БД: вчерашний курс, чтобы показать динамику стрелочкой. Храним в БД,
# а не в памяти - иначе после каждого перезадеплоя «вчерашний» курс терялся бы.
_PREV_RATE_KEY = "fx_usd_yesterday"

TZ = ZoneInfo(WEATHER_TZ)

_WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница",
             "суббота", "воскресенье"]
_MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
           "августа", "сентября", "октября", "ноября", "декабря"]

# Коды погоды WMO - общие для всей метеослужбы, Open-Meteo отдаёт именно их.
_WMO = {
    0: ("ясно", "☀️"), 1: ("в основном ясно", "🌤"), 2: ("переменная облачность", "⛅"),
    3: ("пасмурно", "☁️"), 45: ("туман", "🌫"), 48: ("изморозь", "🌫"),
    51: ("морось", "🌦"), 53: ("морось", "🌦"), 55: ("сильная морось", "🌧"),
    56: ("ледяная морось", "🌧"), 57: ("ледяная морось", "🌧"),
    61: ("небольшой дождь", "🌦"), 63: ("дождь", "🌧"), 65: ("сильный дождь", "🌧"),
    66: ("ледяной дождь", "🌧"), 67: ("ледяной дождь", "🌧"),
    71: ("небольшой снег", "🌨"), 73: ("снег", "❄️"), 75: ("сильный снег", "❄️"),
    77: ("снежные зёрна", "🌨"), 80: ("ливень", "🌦"), 81: ("ливень", "🌧"),
    82: ("сильный ливень", "⛈"), 85: ("снег с дождём", "🌨"), 86: ("снег с дождём", "🌨"),
    95: ("гроза", "⛈"), 96: ("гроза с градом", "⛈"), 99: ("гроза с градом", "⛈"),
}


def _wmo(code):
    """Описание и эмодзи по коду WMO. Неизвестный код не роняет сводку."""
    try:
        return _WMO.get(int(code), ("переменная облачность", "🌡"))
    except (TypeError, ValueError):
        return ("переменная облачность", "🌡")


def _degrees(value) -> str:
    """+7°, -3°, 0° - по-человечески, с округлением до целого."""
    try:
        value = int(round(float(value)))
    except (TypeError, ValueError):
        return "?"
    return f"{value:+d}°" if value else "0°"


def _number(value, digits: int = 4) -> str:
    """Число с запятой как в русском: 2,9883."""
    try:
        text = f"{float(value):.{digits}f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return "?"
    return text.replace(".", ",")


def _hour_of(stamp: str) -> int:
    """Из '2026-10-21T13:00' делаем 13. Не разбираем - возвращаем -1."""
    match = re.search(r"T(\d{2}):", stamp or "")
    return int(match.group(1)) if match else -1


# ===== ПОГОДА =====
async def _fetch_json(url: str, params: dict = None):
    timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT)
    headers = {"User-Agent": USER_AGENT}
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, params=params) as resp:
            if resp.status != 200:
                cl.log("Weather", "warning", f"{resp.status} от {url.split('/')[2]}")
                return None
            return await resp.json(content_type=None)


def _parts(hourly: dict) -> list:
    """
    Разкладывает почасовой прогноз на утро/день/вечер/ночь.
    Для каждого куска: температура от и до, самая частая погода и максимальная
    вероятность осадков. Границы условные, но привычные человеку.
    """
    times = (hourly or {}).get("time") or []
    temps = (hourly or {}).get("temperature_2m") or []
    codes = (hourly or {}).get("weather_code") or []
    probs = (hourly or {}).get("precipitation_probability") or []
    if not times or not temps:
        return []

    slots = (
        ("Утро", (5, 11), "🌅"),
        ("День", (12, 17), "☀️"),
        ("Вечер", (18, 22), "🌇"),
        ("Ночь", (23, 4), "🌙"),
    )
    result = []
    for name, (start, end), emoji in slots:
        part_temps, part_codes, part_probs = [], [], []
        for index, stamp in enumerate(times):
            hour = _hour_of(stamp)
            if hour < 0:
                continue
            inside = hour >= start if start <= end else (hour >= start or hour <= end)
            if not inside:
                continue
            if index < len(temps) and temps[index] is not None:
                part_temps.append(float(temps[index]))
            if index < len(codes) and codes[index] is not None:
                part_codes.append(codes[index])
            if index < len(probs) and probs[index] is not None:
                part_probs.append(float(probs[index]))
        if not part_temps:
            continue

        # Самая частая погода за кусок дня: модa, без хитростей
        common = max(set(part_codes), key=part_codes.count) if part_codes else 0
        description, _ = _wmo(common)
        line = (f"{emoji} {name}: {_degrees(min(part_temps))}...{_degrees(max(part_temps))}, "
                f"{description}")
        if part_probs and max(part_probs) >= 30:
            line += f", осадки до {int(max(part_probs))}%"
        result.append(line)
    return result


async def weather_text() -> str | None:
    """Погода в городе на сегодня: сейчас, минимум/максимум, части дня, советы."""
    data = await _fetch_json(WEATHER_URL, params={
        "latitude": WEATHER_LAT, "longitude": WEATHER_LON,
        "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,"
                   "relative_humidity_2m,precipitation",
        "hourly": "temperature_2m,precipitation_probability,weather_code",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,"
                 "precipitation_probability_max,wind_speed_10m_max,sunrise,sunset",
        "timezone": WEATHER_TZ, "forecast_days": 1,
    })
    if not data:
        return None

    current = data.get("current") or {}
    daily = data.get("daily") or {}
    if not current and not daily:
        cl.log("Weather", "warning", "Open-Meteo ответил пусто")
        return None

    today = datetime.now(TZ)
    description, emoji = _wmo(current.get("weather_code") or (daily.get("weather_code") or [0])[0])
    # Город в заголовке стоит именительным падежом и без предлога «в»:
    # иначе «Погода в Минск» или «в Гомель», а переклонять город из переменной
    # окружения - верный способ словить бессмыслицу на новом городе.
    # Экранируем: город берётся из переменной окружения, а сообщение уходит
    # с parse_mode=HTML - случайная угловая скобка отвергла бы всё сообщение.
    city = html_lib.escape(WEATHER_CITY)
    lines = [f"{emoji} <b>Погода · {city}</b>, {_WEEKDAYS[today.weekday()]} "
             f"{today.day} {_MONTHS[today.month - 1]}"]

    if current:
        feels = ""
        if current.get("apparent_temperature") is not None and \
                current.get("apparent_temperature") != current.get("temperature_2m"):
            feels = f" (ощущается {_degrees(current['apparent_temperature'])})"
        lines.append(f"Сейчас {_degrees(current.get('temperature_2m'))}{feels}, {description}")
        details = []
        if current.get("wind_speed_10m") is not None:
            details.append(f"ветер {int(round(float(current['wind_speed_10m'])))} км/ч")
        if current.get("relative_humidity_2m") is not None:
            details.append(f"влажность {int(current['relative_humidity_2m'])}%")
        if details:
            lines.append(" · ".join(details))

    if daily.get("temperature_2m_max"):
        lines.append(f"В течение дня: от {_degrees((daily['temperature_2m_min'] or [0])[0])} "
                     f"до {_degrees(daily['temperature_2m_max'][0])}")

    lines += _parts(data.get("hourly"))

    # Восход и закат приходят как '2026-10-21T07:48'
    sun = []
    for key, label in (("sunrise", "восход"), ("sunset", "закат")):
        values = daily.get(key) or []
        if values:
            sun.append(f"{label} {str(values[0])[11:16]}")
    if sun:
        lines.append(" · ".join(sun))

    lines.append(_advice(daily, current))
    return "\n".join(lines)


def _advice(daily: dict, current: dict) -> str:
    """
    Бытовой вывод из цифр: зонт, одежда. Прогноз без рекомендации - это таблица,
    а человек читает сообщение ради ответа на «что надеть и брать ли зонт».
    """
    tips = []
    try:
        rain_chance = float((daily.get("precipitation_probability_max") or [0])[0] or 0)
        rain_mm = float((daily.get("precipitation_sum") or [0])[0] or 0)
    except (TypeError, ValueError):
        rain_chance, rain_mm = 0, 0
    if rain_chance >= 50 or rain_mm >= 2:
        tips.append("зонт точно бери ☔️")
    elif rain_chance >= 30 or rain_mm >= 0.5:
        tips.append("зонт на всякий случай 🌂")

    try:
        cold = float((daily.get("temperature_2m_min") or [10])[0])
    except (TypeError, ValueError):
        cold = 10
    if cold <= 0:
        tips.append("ниже нуля — тёплые вещи и обувь потеплее 🧣")
    elif cold < 8:
        tips.append("куртка и шарф не помешают 🧥")
    elif cold < 14:
        tips.append("лёгкая куртка сверху 🧥")

    try:
        wind = float((daily.get("wind_speed_10m_max") or [0])[0] or 0)
    except (TypeError, ValueError):
        wind = 0
    if wind >= 25:
        tips.append(f"ветрено, до {int(round(wind))} км/ч 💨")

    if not tips:
        return "День спокойный — гуляй и не мёрзни 💋"
    return "Совет: " + ", ".join(tips) + " 💋"


# ===== КУРС ВАЛЮТЫ =====
async def currency_text() -> str | None:
    """Официальный курс доллара Нацбанка РБ + динамика к прошлому значению."""
    data = await _fetch_json(NBRB_RATE_URL.format(currency_id=FX_USD_ID))
    if not isinstance(data, dict):
        return None
    rate = data.get("Cur_OfficialRate")
    try:
        rate = float(rate)
    except (TypeError, ValueError):
        cl.log("Weather", "warning", f"NBRB вернул курс без числа: {str(data)[:120]}")
        return None
    scale = data.get("Cur_Scale") or 1
    try:
        rate = rate / float(scale)
    except (TypeError, ValueError, ZeroDivisionError):
        pass

    line = f"💵 <b>1 USD = {_number(rate)} BYN</b> — официальный курс НБ РБ"
    date = str(data.get("Date") or "")
    if len(date) >= 10:
        month = int(date[5:7]) - 1
        if 0 <= month < 12:
            line += f" на {int(date[8:10])} {_MONTHS[month]}"

    # Динамику считаем от того же курса, что показывали вчера. Храним в БД,
    # чтобы стрелка не пропадала после перезадеплоя.
    try:
        previous = BotState.get_value(_PREV_RATE_KEY)
        BotState.set_value(_PREV_RATE_KEY, str(rate))
    except Exception:
        previous = None
        cl.log("Weather", "warning", "не смог прочитать/записать вчерашний курс")
    if previous:
        try:
            delta = rate - float(previous)
        except (TypeError, ValueError):
            delta = 0
        if abs(delta) >= 0.0005:
            arrow = "▲ доллар растёт" if delta > 0 else "▼ доллар сдаёт"
            line += f"\nЗа сутки {'+' if delta > 0 else '−'}{_number(abs(delta))} — {arrow}"
        else:
            line += "\nЗа сутки почти не изменился 😌"
    return line


# ===== СВОДКА =====
async def morning_digest() -> str | None:
    """
    Одно утреннее сообщение: погода + доллар.
    Если оба источника молчат - возвращаем None, сводка в этом дне не приходит.
    """
    results = await asyncio.gather(weather_text(), currency_text(), return_exceptions=True)
    parts = []
    for name, item in zip(("погода", "валюта"), results):
        if isinstance(item, Exception):
            # Исключение одного куска не должно топить всю сводку
            cl.log("Weather", "error", f"{name}: {traceback.format_exc()[-300:]}")
            continue
        if item:
            parts.append(item)
    if not parts:
        cl.log("Weather", "warning", "ни погода, ни курс не пришли - сводку пропускаю")
        return None
    if len(parts) == 1:
        parts.append("Вторую половину сводки сеть не отдала 🙈")
    return "\n\n".join(parts)
