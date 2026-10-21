"""
Собственный мини-мозг бота. Без ключей, без интернета, без лимитов и без оплаты.

Честно про «сделать своего DeepSeek»: настоящую нейросеть тут не построить -
это терабайты текстов, GPU-кластеры и недели обучения. Зато можно построить
понятный движок на правилах: он мгновенно считает, знает дату и время,
рассказывает про самого себя, считает текст, гадает и отвечает на бытовые
вопросы. Это последняя ступень в каскаде managers/ai.py: когда DeepSeek нет
или сеть молчит, бот всё равно отвечает по делу, а не молчит.

Правило договора: каждый обработчик возвращает готовый текст ответа либо None,
если вопрос ему не по зубам. Тогда слово берёт следующий канал каскада.
"""

import ast
import math
import random
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from managers import content
from storage.config import TIMEZONE

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
    "— сказать дату и время: «который час», «какое сегодня число»\n"
    "— погадать: «подбрось монетку», «случайное число от 1 до 100», «да или нет»\n"
    "— поработать с текстом: «переверни строку», «сколько букв в слове ...»\n"
    "— прислать стих, признание, комплимент или обнимашки\n"
    "— открыть меню: /start, /menu, /help, /settings\n\n"
    "А ещё я храню нашу историю любви — она в разделе «О нас» 💕"
)


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
    return None


def answer(text: str, user_name: str = None, hard_only: bool = False) -> str | None:
    """
    Пробует ответить на сообщение своими силами.
    Возвращает текст либо None - тогда каскад спрашивает внешнюю модель.

    hard_only=True оставляет только детерминированные ответы (арифметика, дата,
    гадание, работа с текстом). Их имеет смысл спрашивать у себя ПЕРВЫМИ:
    ответ точный, мгновенный и не тратит ни лимиты бесплатного канала,
    ни платные токены. Болтовню же при hard_only отдаём наружу, чтобы
    «привет, расскажи про космос» не превратилось в дежурное «привет».
    """
    raw = (text or "").strip()
    if not raw:
        return None
    norm = _norm(raw)

    handlers = [
        # Первыми идут точные вычисления: «2+2» не должен перехватывать болтовня.
        lambda: _math(raw, norm),
        lambda: _datetime_answer(norm),
        lambda: _random_answer(norm),
        lambda: _text_tools(raw, norm),
    ]
    if not hard_only:
        handlers += [
            lambda: _content_request(norm),
            lambda: _small_talk(raw, norm, user_name),
        ]

    for handler in handlers:
        try:
            reply = handler()
        except Exception:
            reply = None
        if reply:
            return reply

    if hard_only:
        return None

    # Совсем не понял: не молчим, но и не вводим в заблуждение.
    if len(norm.split()) <= 2:
        return (f"{content.next_compliment()}\n\n"
                "Спроси подробнее или напиши «что умеешь» 💋")
    return None
