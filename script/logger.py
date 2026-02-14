import logging
import os
import re
import sys
import json
import time
import traceback
from logging.handlers import RotatingFileHandler
from datetime import datetime

# Попытка импорта colorama
try:
    from colorama import Fore, Style, init
    init(autoreset=True)
    COLOR_AVAILABLE = True
except ImportError:
    COLOR_AVAILABLE = False

ANSI_ESCAPE = re.compile(r'\x1B(?:[@-Z\\\\-_]|\[[0-?]*[ -/]*[@-~])')

_DESCRIPTIONS = {
    'init_start': "[CORE] Начало инициализации...",
    'init_done': "[CORE] Инициализация завершена.",
    'region_start': "\n[CORE] Начинаю работу с регионом {index}/{total}: {name} ({lang})",
    'type_text': " -> Ввод текста: '{text}'",
    'send_messages_start': " -> Отправка сообщений...",
    'send_message': " - Сообщение {number}: {text}",
    'region_success': "[CORE] Работа с регионом {name} успешно завершена.",
    'typo_generated': "[TYPO] Сгенерирована опечатка: '{original}' -> '{modified}'",
    'chat_pos': " -> Активация окна/чата",
    'channel_join_pos': " -> Вступить в канал",
    'channel_region_pos': " -> Открыть список регионов",
    'channel_find_pos': " -> Активировать поиск региона",
    'channel_accept_pos': " -> Выбрать найденный канал",
    'channel_leave_pos': " -> Покинуть канал",
    'main_cooldown': "\n[CORE] Все регионы пройдены. Начинаю большой кулдаун..."
}

def strip_ansi(text):
    return ANSI_ESCAPE.sub('', text)

# --- ФИЛЬТР ДЛЯ КОНСОЛИ ---
class ConsoleFilter(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        # Блокируем [WORKER] и [TRACE] для вывода в консоль (меню)
        # Они будут записаны только в файл лога
        if "[WORKER]" in msg: 
            return False
        if "[TRACE]" in msg: 
            return False
        return True

def setup_logging(console_level=logging.INFO, file_level=logging.DEBUG):
    log_directory = "logs"
    dump_directory = os.path.join(log_directory, "debug_dumps")

    if not os.path.exists(log_directory): 
        os.makedirs(log_directory)
    if not os.path.exists(dump_directory): 
        os.makedirs(dump_directory)

    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    log_filename = f"run_{timestamp}.log"
    log_file_path = os.path.join(log_directory, log_filename)

    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    if logger.hasHandlers(): 
        logger.handlers.clear()

    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%H:%M:%S')

    # --- FILE HANDLER (Пишет всё, включая TRACE и WORKER) ---
    file_handler = RotatingFileHandler(log_file_path, maxBytes=5*1024*1024, backupCount=5, encoding='utf-8')
    file_handler.setLevel(file_level)
    file_handler.setFormatter(formatter)

    # --- CONSOLE HANDLER (Фильтрует лишнее через ConsoleFilter) ---
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(console_level)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(ConsoleFilter())

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    logging.info(f"[Logger] Лог-файл: {log_filename}")

def log_event(key, **kwargs):
    if key in _DESCRIPTIONS: 
        message = _DESCRIPTIONS[key].format(**kwargs)
    else:
        context = f" ({kwargs})" if kwargs else ""
        message = f" -> {key}{context}"
    logging.info(message)

def log_worker(colored_message, level="INFO", print_to_console=True):
    clean_message = strip_ansi(colored_message)

    if print_to_console:
        print(colored_message)

    if level.upper() == "ERROR": 
        logging.error(f"[WORKER] {clean_message}")
    elif level.upper() == "DEBUG": 
        logging.debug(f"[WORKER] {clean_message}")
    else: 
        logging.info(f"[WORKER] {clean_message}")

def log_debug(message, component="SYSTEM"):
    logging.debug(f"[{component}] {strip_ansi(message)}")

def log_error(message, component="SYSTEM"):
    logging.error(f"[{component}] {strip_ansi(message)}")

# --- СИСТЕМА ДАМПОВ ---
def log_response_dump(response, steam_id, stage="Unknown", reason="Error", exception_obj=None):
    """
    Сохраняет полный дамп: НАШ ЗАПРОС + ОТВЕТ СЕРВЕРА.
    """
    try:
        dump_dir = os.path.join("logs", "debug_dumps")
        if not os.path.exists(dump_dir): 
            os.makedirs(dump_dir)

        timestamp = datetime.now().strftime('%H-%M-%S_%f')
        safe_sid = str(steam_id).replace("/", "").replace(":", "")
        status_code = getattr(response, 'status_code', 0) if response else 0
        filename = f"{stage}_{safe_sid}_{status_code}_{timestamp}.json"
        filepath = os.path.join(dump_dir, filename)

        # --- СБОР ДАННЫХ ---
        dump_data = {
            "meta": {
                "timestamp": time.time(),
                "time_human": datetime.now().isoformat(),
                "steam_id": steam_id,
                "stage": stage,
                "reason": reason
            },
            "request": {},
            "response": {},
            "exception": str(exception_obj) if exception_obj else None,
            "traceback": traceback.format_exc() if exception_obj else None
        }

        if response:
            # 1. ОТВЕТ (Response)
            dump_data["response"]["url"] = getattr(response, 'url', 'N/A')
            dump_data["response"]["status_code"] = status_code
            dump_data["response"]["elapsed"] = str(getattr(response, 'elapsed', 0))

            headers_resp = {}
            raw_headers_resp = getattr(response, 'headers', {})
            try:
                if hasattr(raw_headers_resp, 'items'): 
                    headers_resp = dict(raw_headers_resp.items())
                else: 
                    headers_resp = dict(raw_headers_resp)
            except: 
                headers_resp = str(raw_headers_resp)

            dump_data["response"]["headers"] = headers_resp

            try:
                if hasattr(response, 'cookies'):
                    dump_data["response"]["cookies"] = response.cookies.get_dict() if hasattr(response.cookies, 'get_dict') else dict(response.cookies)
            except: 
                pass

            try: 
                dump_data["response"]["body"] = response.text
            except: 
                dump_data["response"]["body"] = "[Binary/Error]"

            # 2. ЗАПРОС (Request)
            req = getattr(response, 'request', None)
            if req:
                dump_data["request"]["method"] = getattr(req, 'method', 'N/A')
                dump_data["request"]["url"] = getattr(req, 'url', 'N/A')

                headers_req = {}
                raw_headers_req = getattr(req, 'headers', {})
                try:
                    if hasattr(raw_headers_req, 'items'): 
                        headers_req = dict(raw_headers_req.items())
                    else: 
                        headers_req = dict(raw_headers_req)
                except: 
                    headers_req = str(raw_headers_req)

                dump_data["request"]["headers"] = headers_req
                dump_data["request"]["body"] = str(getattr(req, 'body', ''))
            else:
                dump_data["request"] = "Not Available (Request object missing)"

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(dump_data, f, indent=4, ensure_ascii=False)

        if COLOR_AVAILABLE:
            prefix = f"{Fore.RED}[DUMP]" if exception_obj else f"{Fore.YELLOW}[DUMP]"
            print(f"{prefix} Saved: {Style.BRIGHT}.../{filename}{Style.RESET_ALL}")
        else:
            print(f"[DUMP] Saved: logs/debug_dumps/{filename}")

    except Exception as e:
        log_error(f"FAILED TO SAVE DUMP: {e}", component="Logger")

def save_crash_dump(steam_id, proxy_url, status_code, headers, body_content, reason="Unknown"):
    log_response_dump(None, steam_id, stage="ManualDump", reason=reason)

# ============================================================================
# НОВАЯ ФУНКЦИЯ: ЛОГИРОВАНИЕ ВЫСОКИХ ИНВЕНТАРЕЙ
# ============================================================================

def log_high_value_inventory(steam_id, nickname, price, threshold=300):
    """
    Записывает Steam ID в resultlog.txt если инвентарь >= threshold

    :param steam_id: Steam ID64
    :param nickname: Никнейм пользователя
    :param price: Стоимость инвентаря
    :param threshold: Минимальная стоимость для записи (по умолчанию 300)
    """
    try:
        if price < threshold:
            return

        result_file = "resultlog.txt"
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Формат записи: [Дата] Steam_ID | Nickname | Price
        entry = f"[{timestamp}] {steam_id} | {nickname} | {int(price)} ₽\n"

        # Проверяем, существует ли файл
        file_exists = os.path.exists(result_file)

        # Записываем в файл (append mode)
        with open(result_file, 'a', encoding='utf-8') as f:
            # Если файл новый - добавляем заголовок
            if not file_exists:
                f.write("# Высокие инвентари (>= 300₽)\n")
                f.write("# Формат: [Дата] Steam_ID | Nickname | Price\n")
                f.write("-" * 80 + "\n")

            f.write(entry)

        # Логируем факт записи
        if COLOR_AVAILABLE:
            log_msg = f"{Fore.GREEN}[RESULT] {Style.BRIGHT}Added to resultlog.txt:{Style.RESET_ALL} {nickname} ({int(price)}₽)"
        else:
            log_msg = f"[RESULT] Added to resultlog.txt: {nickname} ({int(price)}₽)"

        logging.info(log_msg)

    except Exception as e:
        log_error(f"Failed to write to resultlog.txt: {e}", component="Logger")
