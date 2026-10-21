"""
Собственный мини-мозг бота. Без ключей, без интернета, без лимитов и без оплаты.

Честно про «сделать своего DeepSeek»: настоящую нейросеть тут не построить -
это терабайты текстов, GPU-кластеры и недели обучения. Зато можно построить
понятный движок на правилах: он мгновенно считает, знает дату и время,
рассказывает про самого себя, считает текст, гадает и отвечает на бытовые
вопросы. Это последняя ступень в каскаде managers/ai.py: когда DeepSeek нет
или сеть молчит, бот всё равно отвечает по делу, а не молчит.

Правило договора: точные ответы отдаём всегда; болтовню - только когда
режим не hard_only. Вызов без hard_only отвечает на ЛЮБОЕ сообщение, пусть
даже честным «не знаю»: бот не молчит и не закидывает пользователя
комплиментами вместо ответа.
"""

import ast
import math
import random
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from managers import content
from storage.config import TIMEZONE, MEME_MIN

TZ = ZoneInfo(TIMEZONE)

# Операторы нашего калькулятора. Всё остальное ast не пропустит.
_ALLOWED_BINOPS = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/",
                   ast.FloorDiv: "//", ast.Mod: "%", ast.Pow: "**"}
_ALLOWED_UNARY = {ast.UAdd: "+", ast.USub: "-"}

_WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница",
             "суббота", "воскресенье"]
_MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
           "августа", "сентября", "октября", "ноября", "декабря"]

_ANSWER_YES_NO = ["Да 💋", "Однозначно да 💖", "Конечно, любимая 💕", "Наверное, да 🤔",
                  "Пока не знаю, но склоняюсь к «да» 🍌", "Лучше пока нет 🥺",
                  "Точно нет 💔", "Спроси ещё раз позже 😌"]

_ABOUT_ME = (
    "Я Аднунка-Бананка 🍌💋 Твой личный бот: обнимаю, напоминаю и отвечаю "
    "на вопросы.\n\n"
    "Что умею:\n"
    "— посчитать: «2+2*2», «5% от 200», «корень из 144»\n"
    "— перевести единицы: «сколько минут в 3 часах», «2 кг это сколько грамм»\n"
    "— сказать дату и время: «который час», «какое сегодня число», "
    "«сколько дней до 14 февраля»\n"
    "— погадать: «подбрось монетку», «случайное число от 1 до 100», «да или нет»\n"
    "— поработать с текстом: «переверни строку», «сколько букв в слове ...»\n"
    "— прислать стих, признание, комплимент или обнимашки\n"
    "— каждые {MEME_MIN} минут приносить самый смешной мем 😂\n"
    "— открыть меню: /start, /menu, /help, /settings\n\n"
    "А ещё я храню нашу историю любви — она в разделе «О нас» 💕"
).replace("{MEME_MIN}", str(MEME_MIN))

# Элементы флирта. Пользователь просил отвечать ЧЁТКО по вопросу, но с
# нежностью: поэтому сначала всегда идёт суть, а хвост-флирт короткий и
# НЕ к каждому ответу (иначе через три сообщения он выглядит как приписка).
_FLIRT_TAILS = [
    "💋",
    "Целую 😚",
    "Обнимаю крепко 🤗",
    "Ты сегодня очень красивая, знаешь об этом? 💖",
    "Рядом с тобой даже цифры приятные 💋",
    "Скучаю, пока ты молчишь 🍌",
    "Всё для тебя 😌",
    "Хочу тебя увидеть поскорее 💕",
]
_flirt_deck = content.Deck(_FLIRT_TAILS)


def _flirt(text: str, chance: float = 0.55) -> str:
    """Добавляет короткий нежный хвост к готовому ответу."""
    if not text or random.random() >= chance:
        return text
    return f"{text} {_flirt_deck.next()}"


# ===== МИНИ-БАЗА ЗНАНИЙ =====
# Не энциклопедия, а то, о чём нас реально спрашивают каждый день.
# Факты здесь проверенные и общие; на всё остальное каскад зовёт модель,
# а если сети нет - честное «не знаю» вместо красивого, но пустого текста.
_KNOWLEDGE = [
    (("кто такая даша", "кто такой аднан", "расскажи про нас", "про дашу и аднана",
      "наша история"),
     "Даша и Аднан — пара, про которую я и написана 💋 Он — тот самый банан, "
     "который динамил, а потом не выдержал и написал в 3:47 ночи.\n\n"
     "Вся история по главам — в меню, раздел «О нас» 💕"),
    (("как извиниться", "поссорились", "как помириться", "обидел", "обидела"),
     "Извиняются так: без «но» и без «если ты тоже».\n"
     "1. Назвать конкретно, что сделал не так.\n"
     "2. Сказать, как это задело человека.\n"
     "3. Предложить, как исправишь.\n\n"
     "И не ждать мгновенного прощения — дать человеку время. "
     "Напиши первым, я за тебя поручусь 💋"),
    (("что подарить", "что купить в подарок", "идея подарка"),
     "Подарки делятся на три кита: полезное, вкусное, памятное. Работает лучше "
     "всего комбинация: мелочь, которая говорит «я тебя слушал» (книжка, которую "
     "ты упомянула три недели назад), плюс цветы или что-то сладкое.\n\n"
     "Дорого — не значит хорошо. Внимание — значит внимание 💋"),
    (("как признаться", "сказать что люблю", "признаться в любви"),
     "Признание работает, когда оно короткое и своё: «я понял, что скучаю по тебе "
     "каждый день» сильнее, чем стих на две страницы.\n\n"
     "Скажи это вживую и без «это ни к чему не обязывает». Я могу подготовить "
     "текст — напиши «напиши признание» 💋"),
    (("что такое любовь", "как понять что люблю", "это любовь"),
     "Простой тест: тебе важно не только то, что тебе хорошо с человеком, но и то, "
     "хорошо ли ему с тобой. Плюс спокойствие — без постоянных качелей.\n\n"
     "Страсть громкая, любовь тихая. Если с человеком можно молчать и не "
     "напрягаться — это оно 💕"),
    (("как успокоиться", "тревога", "нервничаю", "стресс", "как снять стресс"),
     "Быстрое: дыхание 4-4-6 (вдох 4, держать 4, выдох 6) минут пять — выдох "
     "длиннее вдоха реально тормозит пульс.\n\n"
     "Дальше — вода, еда и 20 минут прогулки. Тревога почти всегда громче, "
     "когда ты не выспалась. Я рядом, расскажешь что случилось? 💋"),
    (("не спится", "не могу уснуть", "бессонница"),
     "Убери телефон (да-да, я про это), сделай комнату холоднее и темнее, а если "
     "через 20 минут не уснула — встань, почитай бумажное, вернись.\n\n"
     "И не смотри на часы. Напиши мне — я побуду рядом, пока не уснёшь 🌙"),
    (("что посмотреть", "чем заняться", "идея для свидания", "куда сходить",
      "что делать вечером"),
     "Идеи, которые не надоедают: прогулка с наушником на двоих и плейлистом, "
     "который вы собирали вместе; готовка блюда из страны, где никогда не были; "
     "«вечер воспоминаний» — пересматриваете старые переписки и фотки.\n\n"
     "Главное не место, а что вы не в телефонах 💋"),
    (("что приготовить", "что поесть", "что готовить"),
     "Быстро и не стыдно: паста с чесноком и маслом + сыр + зелень (15 минут); "
     "рис с яйцом и соевым соусом; омлет с помидорами.\n\n"
     "Если есть конкретные продукты — напиши, что в холодильнике, "
     "и я соберу из этого ужин 💋"),
    (("как понять что человек любит", "как понять что я ему нравлюсь"),
     "Смотрят на поступки в мелочах: помнит ли то, что ты говорила между делом, "
     "находит ли время, когда занят, защищает ли тебя в разговорах за твоей "
     "спиной.\n\n"
     "Слова — это погода, привычка помнить о тебе — это климат 💋"),
]

# Конвертации единиц: «сколько минут в 3 часах».
# (множитель к базовой единице, все падежи, которые люди пишут)
_UNIT_GROUPS = [
    ("секунд", [
        (1, ("секунда", "секунды", "секунд", "секунду", "секунде", "секундах", "сек", "с")),
        (60, ("минута", "минуты", "минут", "минуту", "минуте", "минутах", "мин")),
        (3600, ("час", "часа", "часов", "часу", "часе", "часах", "ч")),
        (86400, ("сутки", "суток", "суткам", "сутках", "день", "дня", "дней", "дню", "днях")),
        (604800, ("неделя", "недели", "недель", "неделю", "неделе", "неделях")),
        (2678400, ("месяц", "месяца", "месяцев", "месяцу", "месяце", "месяцах")),
        (31536000, ("год", "года", "лет", "году", "годе", "годах")),
    ]),

    ("м", [
        (0.001, ("миллиметр", "миллиметра", "миллиметров", "миллиметре", "миллиметрах", "мм")),
        (0.01, ("сантиметр", "сантиметра", "сантиметров", "сантиметре", "сантиметрах", "см")),
        (1, ("метр", "метра", "метров", "метре", "метрах", "м")),
        (1000, ("километр", "километра", "километров", "километре", "километрах", "км")),
    ]),
    ("г", [
        (1, ("грамм", "грамма", "граммов", "грамме", "граммах", "г")),
        (1000, ("килограмм", "килограмма", "килограммов", "килограмме", "килограммах", "кг")),
        (1000000, ("тонна", "тонны", "тонн", "тонну", "тонне", "тоннах", "т")),
    ]),
]


def _norm(text: str) -> str:
    """
    Нижний регистр, ё -> е, мусорная пунктуация в пробелы.
    Арифметику (+ - * / % ^ скобки, точка и запятая в числах) сохраняем:
    иначе «2+2» превращается в «2 2» и калькулятор ничего не находит.
    """
    text = text.lower().replace("ё", "е")
    return re.sub(r"[^\w\s%\.\,\+\-\*\/\^\(\)]", " ", text)


def _has(text: str, *words) -> bool:
    """Встречается ли хоть одно слово целиком (не куском другого слова)."""
    return any(re.search(rf"\b{re.escape(w)}\b", text) for w in words)


# ===== АРИФМЕТИКА =====
def _safe_eval(node):
    """Вычисляет выражение из чисел и +-*/%//**, не давая выполнить код."""
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
        left, right = _safe_eval(node.left), _safe_eval(node.right)
        if isinstance(node.op, ast.Pow) and (abs(right) > 64 or abs(left) > 10 ** 9):
            raise ValueError("слишком большая степень")
        if isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)) and right == 0:
            raise ZeroDivisionError
        return _apply(node.op, left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARY:
        value = _safe_eval(node.operand)
        return value if isinstance(node.op, ast.UAdd) else -value
    raise ValueError("разрешены только числа и + - * / // % **")


def _apply(op, left, right):
    if isinstance(op, ast.Add):
        return left + right
    if isinstance(op, ast.Sub):
        return left - right
    if isinstance(op, ast.Mult):
        return left * right
    if isinstance(op, ast.Div):
        return left / right
    if isinstance(op, ast.FloorDiv):
        return left // right
    if isinstance(op, ast.Mod):
        return left % right
    return left ** right


def _pretty(number) -> str:
    """Красиво печатаем число: без хвоста .0 и с разделителями разрядов."""
    if isinstance(number, float):
        if number != number or number in (float("inf"), float("-inf")):
            return "не могу — получается бесконечность 🙈"
        number = round(number, 6)
        if number == int(number):
            number = int(number)
        else:
            return f"{number}".rstrip("0").rstrip(".")
    return f"{number:,}".replace(",", " ")


def _math(raw: str, norm: str):
    """Проценты, корень, степень и обычные выражения вида 17*23 или (5+3)*2**3."""
    percent = re.search(r"(\d+(?:[.,]\d+)?)\s*%.*?(\d+(?:[.,]\d+)?)", norm)
    if percent and ("от" in norm or "из" in norm):
        part = float(percent.group(1).replace(",", "."))
        whole = float(percent.group(2).replace(",", "."))
        return f"{_pretty(part)}% от {_pretty(whole)} = {_pretty(whole * part / 100)} 🧮"

    root = re.search(r"(?:корень|sqrt)\s*(?:из)?\s*(\d+(?:[.,]\d+)?)", norm)
    if root:
        value = float(root.group(1).replace(",", "."))
        if value < 0:
            return "Корень из отрицательного числа — только в стране мнимых снов 🌀"
        return f"√{_pretty(value)} = {_pretty(math.sqrt(value))} 🧮"

    # Ищем куски, похожие на выражение: цифры, скобки и операторы подряд.
    # Оператор % в общий калькулятор не берём: «100% любви» не должно
    # считаться остатком от деления.
    for chunk in re.findall(r"[\d\.\,\+\-\*\/\^\(\)\s]+", norm.replace(",", ".")):
        expr = chunk.strip().replace(" ", "").replace("^", "**")
        # Оператор должен стоять между операндами. Иначе «-3 градуса»
        # обидно считается выражением и даёт «3 = 3».
        # Многосимвольные операторы (** и //) учитываем отдельно.
        if not re.search(r"[\d)](?:\*{1,2}|/{1,2}|[-+])[\d(]", expr):
            continue
        if expr.count(")") != expr.count("("):
            continue
        try:
            result = _safe_eval(ast.parse(expr, mode="eval"))
        except ZeroDivisionError:
            return "На ноль делить нельзя — даже мне 💔"
        except (ValueError, SyntaxError, RecursionError, MemoryError):
            continue
        return f"{expr} = {_pretty(result)} 💋"
    return None


# ===== ДАТА И ВРЕМЯ =====
def _datetime_answer(norm: str):
    now = datetime.now(TZ)
    if _has(norm, "который час", "сколько времени", "который сейчас час"):
        return f"Сейчас {now.strftime('%H:%M')} по нашему времени ({TIMEZONE}) ⏰"
    if _has(norm, "какой сегодня день", "какой день недели"):
        return f"Сегодня {_WEEKDAYS[now.weekday()]}, {now.day} {_MONTHS[now.month - 1]} 📅"
    if _has(norm, "какое сегодня число", "какая дата", "какое число", "сегодняшнее число"):
        return f"На календаре {now.day} {_MONTHS[now.month - 1]} {now.year} года, " \
               f"{_WEEKDAYS[now.weekday()]} 📅"
    if _has(norm, "который час в москве", "время в москве"):
        return f"В Москве {datetime.now(ZoneInfo('Europe/Moscow')).strftime('%H:%M')} ⏰"
    if _has(norm, "сколько дней до нового года"):
        next_year = datetime(now.year + 1, 1, 1, tzinfo=TZ)
        days = (next_year - now).days
        return f"До Нового года осталось {days} " \
               f"{_plural(days, ('день', 'дня', 'дней'))} 🎄💋"
    return None


def _plural(count: int, forms) -> str:
    """'1 день, 2 дня, 5 дней' — без этого русская фраза сразу-machine."""
    n = abs(count) % 100
    one = n % 10
    if 11 <= n <= 14:
        return forms[2]
    if one == 1:
        return forms[0]
    if 2 <= one <= 4:
        return forms[1]
    return forms[2]


# ===== СЛУЧАЙНОЕ =====
def _random_answer(norm: str):
    if _has(norm, "монетк", "орел", "решк", "подбрось"):
        return f"Выпала {'орёл' if random.random() < 0.5 else 'решка'} 🪙"
    if _has(norm, "гадал", "да или нет", "ответь да"):
        return _ANSWER_YES_NO[random.randrange(len(_ANSWER_YES_NO))]
    dice = re.search(r"кубик(?:\s*(?:от|с)?\s*(\d+))?", norm)
    if dice:
        sides = int(dice.group(1) or 6)
        sides = max(2, min(sides, 1000))
        return f"🎲 {random.randint(1, sides)} (кубик на {sides} граней)"
    rng = re.search(r"(?:случайное|рандомное)?\s*число\s*(?:от|из)?\s*(-?\d+)\s*(?:до|и)\s*(-?\d+)", norm)
    if rng:
        low, high = int(rng.group(1)), int(rng.group(2))
        if low > high:
            low, high = high, low
        return f"Моё число: {random.randint(low, high)} 💋"
    if _has(norm, "случайное число", "назвать число", "угадай число"):
        return f"Мне кажется, это {random.randint(1, 100)} 🍌"
    return None


# ===== РАБОТА С ТЕКСТОМ =====
def _text_tools(raw: str, norm: str):
    if _has(norm, "переверни", "наоборот слово", "задом наперед"):
        quoted = re.search(r"[«\"'](.+?)[»\"']", raw)
        target = quoted.group(1) if quoted else raw.split("переверни")[-1].strip(" :,-")
        target = target or "банан"
        return f"Наоборот будет: «{target[::-1]}» 🔄"

    count = re.search(r"(?:сколько)\s+(?:букв|символов|слов)\s+(?:в )?(?:слове|фразе|предложении|тексте)?\s*[«\"']?(.+?)[»\"']?$",
                      norm)
    if count:
        target = count.group(1).strip()
        if _has(norm, "слов"):
            n = len([w for w in target.split() if w])
            return f"Тут {n} {_plural(n, ('слово', 'слова', 'слов'))} 📝"
        letters = sum(ch.isalpha() for ch in target)
        return f"В «{target}» {letters} {_plural(letters, ('буква', 'буквы', 'букв'))} 📝"

    word = re.search(r"палиндром\s+[«\"']?(\w+)", norm)
    if word:
        w = word.group(1)
        return f"«{w}» — {'да, палиндром! 🪞' if w == w[::-1] else 'не палиндром 🙈'}"
    return None


# ===== КОНВЕРТАЦИИ ЕДИНИЦ =====
def _unit(word: str):
    """Находит единицу по слову пользователя: возвращает (группа, множитель)."""
    for group, units in _UNIT_GROUPS:
        for factor, names in units:
            if word in names:
                return group, factor
    return None


def _pretty_unit(value: float) -> str:
    if value >= 1 or value == 0:
        return _pretty(round(value, 4))
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _convert(norm: str):
    """
    «сколько минут в 3 часах», «2 кг это сколько грамм», «сколько секунд в сутках».
    Число необязательно: «сколько минут в часе» - это про один час.
    Падежи берём у пользователя, поэтому фраза звучит естественно и не требует
    словаря форм.
    """
    m = re.search(r"сколько\s+([a-zа-я]+)\s+(?:в|из)\s*(?:(\d+(?:[.,]\d+)?)\s*)?([a-zа-я]+)", norm)
    reverse = False
    if not m:
        m = re.search(r"(\d+(?:[.,]\d+)?)\s+([a-zа-я]+)\s+(?:это|=)?\s*сколько\s+([a-zа-я]+)", norm)
        reverse = True
    if not m:
        return None

    groups = []
    for word in m.groups():
        # Слова может и не быть: «сколько секунд в сутках» - без числа
        is_number = bool(word) and word.replace(".", "").replace(",", "").isdigit()
        groups.append(None if is_number else _unit(word or ""))
    words = m.groups()
    if reverse:
        value = float(words[0].replace(",", "."))
        src, dst = groups[1], groups[2]
        src_word, dst_word = words[1], words[2]
    else:
        dst, src = groups[0], groups[2]
        value = float(words[1].replace(",", ".")) if words[1] else 1.0
        dst_word, src_word = words[0], words[2]
    if not src or not dst or src[0] != dst[0]:
        return None
    # «сколько секунд в сутках» - числа в вопросе нет, тогда и в ответе
    # «1» не ставим: «в сутках - 86 400 секунд» читается нормально,
    # а «в 1 сутках» - нет.
    amount_given = reverse or bool(words[1])

    result = value * src[1] / dst[1]
    if reverse:
        return f"{_pretty(value)} {src_word} — это {_pretty_unit(result)} {dst_word} 📏"
    if amount_given:
        return f"В {_pretty(value)} {src_word} — {_pretty_unit(result)} {dst_word} 📏"
    return f"В {src_word} — {_pretty_unit(result)} {dst_word} 📏"


# ===== ДАТА ДО =====
def _days_until(norm: str):
    """«сколько дней до 14 февраля» - считает до ближайшей такой даты."""
    m = re.search(r"до\s+(\d{1,2})\s+([a-zа-я]+)", norm)
    if not m:
        return None
    day = int(m.group(1))
    month_name = m.group(2)
    if month_name not in _MONTHS or not 1 <= day <= 31:
        return None
    month = _MONTHS.index(month_name) + 1

    from datetime import date, timedelta
    today = datetime.now(TZ).date()
    try:
        target = date(today.year, month, day)
    except ValueError:
        return None
    if target < today:
        try:
            target = date(today.year + 1, month, day)
        except ValueError:
            return None
    days = (target - today).days
    weeks, rest = divmod(days, 7)
    answer = f"До {day} {month_name} осталось {days} {_plural(days, ('день', 'дня', 'дней'))} 📅"
    if weeks:
        answer += f" — это {weeks} {_plural(weeks, ('неделя', 'недели', 'недель'))}"
        if rest:
            answer += f" и {rest} {_plural(rest, ('день', 'дня', 'дней'))}"
    return answer


# ===== ЗНАНИЯ =====
def _knowledge(norm: str):
    for keys, reply in _KNOWLEDGE:
        if any(key in norm for key in keys):
            return _flirt(reply, chance=0.5)
    return None


# ===== НЕ ПОНЯЛ =====
def _unknown(raw: str, norm: str):
    """
    Последнее слово, когда ни один обработчик не подошёл.
    Комплиментом здесь раньше маскировалось незнание - пользователь видел
    милую фразу и оставался без ответа. Теперь честно: говорим, что не поняли,
    и подсказываем, как спросить.
    """
    words = len(norm.split())
    if words <= 2:
        return _flirt("Слишком коротко, не поняла 🤔 Напиши вопрос целиком — "
                      "посчитаю, переведу единицы, найду дату или просто поболтаю.")
    return _flirt("Точного ответа не знаю и выдумывать не буду 🙈 Напиши этот же "
                  "вопрос через минуту — тогда я успею поискать в сети. Или "
                  "спроси то, что я умею наверняка: «что умеешь» 💋")


# ===== ПРИВЕТЫ И ПРОЩАНИЯ =====
def _small_talk(raw: str, norm: str, user_name: str):
    hello = user_name or "любимая"
    if _has(norm, "привет", "здравствуй", "хай", "доброе утро", "добрый день",
            "добрый вечер", "приветик", "ку"):
        return f"Привет, {hello}! 💋 Я уже скучала. Чем помочь?"
    if _has(norm, "пока", "до свидания", "прощай", "спокойной ночи", "бай"):
        return "Пока-пока 💋 Напиши, как соскучишься — я всегда рядом 🌙"
    if _has(norm, "как дела", "как ты", "как настроение", "как сам"):
        return "У меня всё тепло, раз ты написала 💋 А у тебя как день?"
    if _has(norm, "что делаешь", "чем занимаешься", "ты тут", "ты на месте"):
        return "Жду именно твоего сообщения — и дождалась 💋 Рассказывай"
    if _has(norm, "как меня зовут", "моё имя", "как мое имя"):
        if user_name:
            return f"Тебя зовут {user_name}, и это моё любимое слово 💋"
        return "Telegram не прислал твоё имя, а я не выдумываю 🙈 Напиши, как тебя звать?"
    if _has(norm, "спасибо", "благодарю", "спс"):
        return "Всегда к твоим услугам 💋 Обнимаю крепко 🤗"
    if _has(norm, "люблю", "скучаю", "целую"):
        return "И я тебя 💋 Ты даже не представляешь, как сильно 🍌❤️"
    if _has(norm, "кто ты", "что ты такое", "ты кто", "как тебя зовут"):
        return ("Я Аднунка-Бананка 🍌💋 Твой бот-обнимашка и помощник. "
                "Напиши «что умеешь» — расскажу про все свои фичи.")
    if _has(norm, "что умеешь", "что ты можешь", "помощь", "хелп", "меню", "функции"):
        return _ABOUT_ME
    return None


# ===== ПРОСЬБЫ О КОНТЕНТЕ =====
def _content_request(norm: str):
    if _has(norm, "стих", "стишок"):
        return content.next_poem()
    if _has(norm, "признан", "любви скажи"):
        return content.next_confession()
    if _has(norm, "комплимент", "скажи приятное"):
        return content.next_compliment()
    if _has(norm, "доброе утро"):
        return content.next_morning()
    if _has(norm, "спокойной ночи"):
        return content.next_night()
    if _has(norm, "мем", "мемы", "смешное", "поржи"):
        return ("Мем принести не удалось — похоже, сеть молчит 🙈 Самые смешные "
                f"я приношу сама каждые {MEME_MIN} минут, попробуй ещё раз чуть позже.")
    return None


def _try(handler):
    """Обработчик не имеет права уронить ответ: что-то не разобрал - пропускаем."""
    try:
        return handler()
    except Exception:
        return None


def answer(text: str, user_name: str = None, hard_only: bool = False) -> str | None:
    """
    Пробует ответить на сообщение своими силами.

    hard_only=True оставляет только точные ответы (арифметика, единицы, даты,
    гадание, работа с текстом) и возвращает None для всего остального. Такие
    ответы спрашивают у себя ПЕРВЫМИ: они мгновенные, точные и не тратят ни
    лимиты бесплатного канала, ни платные токены. Болтовню при hard_only не
    отдаём, чтобы «привет, расскажи про космос» не съело весь вопрос.

    Без hard_only движок обязан ответить на ЛЮБОЕ сообщение: он никогда не
    возвращает None. Комплимент сюда больше не подставляется - пользователь
    просил ответ по существу с элементами флирта, а не милую отсебятину.
    """
    raw = (text or "").strip()
    if not raw:
        return None
    norm = _norm(raw)

    # Первыми идут точные вычисления: «2+2» не должен перехватывать болтовня.
    exact = (
        lambda: _math(raw, norm),
        lambda: _convert(norm),
        lambda: _days_until(norm),
        lambda: _datetime_answer(norm),
        lambda: _random_answer(norm),
        lambda: _text_tools(raw, norm),
    )
    # Ответы помягче: то, что уже похоже на беседу.
    soft = (
        lambda: _knowledge(norm),
        lambda: _content_request(norm),
        lambda: _small_talk(raw, norm, user_name),
    )

    for handler in exact:
        reply = _try(handler)
        if reply:
            return _flirt(reply, chance=0.5)

    if hard_only:
        return None

    for handler in soft:
        reply = _try(handler)
        if reply:
            return reply

    return _unknown(raw, norm)
