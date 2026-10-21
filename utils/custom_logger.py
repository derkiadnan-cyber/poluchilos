import logging

from storage.config import DEBUG_MODE
from utils import alerts

log_level = logging.DEBUG if DEBUG_MODE else logging.INFO
logging.basicConfig(level=log_level, format="SCRIPT | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# Уведомляем админа только о серьёзном и не чаще раза в минуту на раздел:
# иначе одна упавшая задача засыпает чат одинаковыми сообщениями.
ALERT_LEVELS = ("warning", "error", "critical")
ALERT_GAP = {
    "warning": 120,
    "error": 60,
    "critical": 10,
}
MAX_MESSAGE = 900


def log(department, level, msg, user_id="SYSTEM"):
    """
    Пишет в лог и (для warning/error/critical) ставит тревогу админам в очередь.
    Функция синхронная, но ничего не ждёт и не бросает исключений: вызывать её
    можно из любого места, включая обработку уже случившейся аварии.
    """
    levels = {
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "warning": logging.WARNING,
        "error": logging.ERROR,
        "critical": logging.CRITICAL
    }
    text = str(msg)
    if len(text) > MAX_MESSAGE:
        text = text[:MAX_MESSAGE] + " …"

    try:
        logger.log(levels.get(level, logging.INFO), f"{department} | {user_id} | {text}")
    except Exception:
        pass

    if level in ALERT_LEVELS:
        alerts.submit(department, f"[{level.upper()}] {user_id} | {text}",
                      gap=ALERT_GAP.get(level, 60))