import time
import random
import re
import html
import traceback
import json
import logging
from colorama import Fore, Style
import logger
from logger import log_response_dump

# --- CONFIG ---
DETAILED_ITEM_LOGGING = True  # ВКЛЮЧЕНО для отладки
TRACE_NETWORK = True  # Включает гипер-подробное логирование сетевых шагов

try:
    from curl_cffi.requests.exceptions import Timeout as CurlTimeout, RequestException
    CURL_AVAILABLE = True
except ImportError:
    from requests.exceptions import Timeout as CurlTimeout, RequestException
    CURL_AVAILABLE = False

# Импорт инстанса переводчика
try:
    from translator import translator_instance
except ImportError:
    translator_instance = None

def _get_time():
    return time.time()

def to_steam_id32(steam_id64):
    try:
        val = int(steam_id64)
        if val > 76561197960265728:
            return str(val - 76561197960265728)
        return str(val)
    except:
        return str(steam_id64)

DOTA_PREFIXES = [
    "Inscribed ", "Corrupted ", "Autographed ", "Auspicious ", "Frozen ",
    "Cursed ", "Exalted ", "Elder ", "Heroic ", "Genuine ", "Infused "
]

def clean_item_name(name):
    clean = name
    for prefix in DOTA_PREFIXES:
        if clean.startswith(prefix):
            clean = clean.replace(prefix, "", 1)
    return clean

def _trace(session_name, msg):
    """Вспомогательная функция для подробного логирования в файл."""
    if TRACE_NETWORK:
        logging.info(f"[{session_name}] [TRACE] {msg}")

def task_ping(session):
    """
    Простой пинг для прогрева соединения/проверки жизни прокси.
    Не возвращает данных, просто делает запрос.
    """
    try:
        session.get_session().get("https://steamcommunity.com", timeout=5)
    except: 
        pass

# --- TASK: TRANSLATION ---
def task_translation(session, text_dummy=None):
    """
    Выполняет задачу перевода через translator_instance.
    """
    if not translator_instance:
        return {"success": False, "text": "No Module"}
    if not translator_instance.is_ready:
        return {"success": False, "text": "Not Ready"}

    start_t = time.time()
    try:
        _trace(session.name, "Starting translation task...")
        result_text = translator_instance.capture_and_translate(mode_flag=text_dummy)
        latency = time.time() - start_t

        if result_text and "Err:" not in result_text:
            msg = f"{Fore.MAGENTA}[Translator]{Style.RESET_ALL} Result ({latency:.2f}s): {result_text}"
            logger.log_worker(msg)
            return {
                "success": True,
                "text": result_text,
                "latency": latency
            }
        else:
            if "Rate Limit" not in result_text:
                logger.log_worker(f"{Fore.RED}[Translator] Failed: {result_text}{Style.RESET_ALL}")
            return {
                "success": False,
                "text": result_text if result_text else "Empty/Error",
                "latency": latency
            }
    except Exception as e:
        logger.log_error(f"Translation Task Error: {e}")
        return {"success": False, "text": "Task Crash"}

# ============================================================================
# НОВАЯ ОБЪЕДИНЕННАЯ ФУНКЦИЯ: ПОИСК НИКА + ПАРСИНГ ИНВЕНТАРЯ
# ============================================================================

def task_full_check(session, steam_id, task_gen_id, prices_db, worker_ref, 
                    attempt=0, timing_config=None, ignore_cache=False):
    """
    ОБЪЕДИНЕННАЯ ЗАДАЧА: Получение ника + Парсинг инвентаря
    1. Получает nickname через XML API
    2. Проверяет историю в log_parser (если ignore_cache=False)
    3. Если в истории нет - парсит инвентарь

    Returns: (result_dict, sid32, session_name, nickname)
    """
    if timing_config is None:
        timing_config = {}

    steam_id_str = str(steam_id)
    sid32 = to_steam_id32(steam_id_str)

    # ==================== ШАГ 1: ПОЛУЧЕНИЕ НИКА ====================
    nickname = None
    _trace(session.name, f"[FULL CHECK] Step 1/3: Fetching nickname for {steam_id_str}")

    try:
        # Если сессия в режиме translator - переключаем обратно
        if session.mode != "steam":
            _trace(session.name, "Switching from Translator -> Steam")
            session.restore_steam_context()

        nick_url = f"https://steamcommunity.com/profiles/{steam_id_str}/?xml=1"
        sess_obj = session.get_session()

        # Запрос за ником
        nick_resp = sess_obj.get(nick_url, timeout=5, verify=False)

        if nick_resp.status_code == 200:
            import html as html_lib
            nick_match = re.search(r'<steamID><!\[CDATA\[(.+?)\]\]></steamID>', nick_resp.text)
            if nick_match:
                nickname = html_lib.unescape(nick_match.group(1))
                _trace(session.name, f"Nickname found: {nickname}")
            else:
                _trace(session.name, "Nickname tag not found in XML")
        else:
            _trace(session.name, f"Nickname fetch failed: HTTP {nick_resp.status_code}")

    except Exception as e:
        _trace(session.name, f"Nickname fetch error: {e}")

    # Если не получили ник - используем ID32 как fallback
    if not nickname:
        nickname = sid32
        _trace(session.name, f"Using fallback nickname: {nickname}")

    # ==================== ШАГ 2: ПРОВЕРКА КЭША (LOG_PARSER) ====================
    if not ignore_cache:
        _trace(session.name, f"[FULL CHECK] Step 2/3: Checking log cache for {nickname}")

        try:
            import log_parser
            if log_parser.parser_instance:
                entry = log_parser.parser_instance.find_entry(nickname)
                if entry:
                    price, currency, date_obj = entry
                    from datetime import datetime
                    days = (datetime.now() - date_obj).days

                    _trace(session.name, f"CACHE HIT: {nickname} = {price} {currency} ({days} days ago)")

                    # Возвращаем результат из кэша
                    return {
                        "success": True,
                        "price": price,
                        "text": f"Cache ({days}д)",
                        "retry": False,
                        "latency": 0,
                        "from_cache": True
                    }, sid32, session.name, nickname
        except Exception as e:
            _trace(session.name, f"Cache check error: {e}")

    # ==================== ШАГ 3: ПАРСИНГ ИНВЕНТАРЯ ====================
    _trace(session.name, f"[FULL CHECK] Step 3/3: Parsing inventory for {nickname}")

    # Вызываем существующую функцию парсинга
    result, sid32_ret, sess_name = task_steam_check(
        session, 
        steam_id_str, 
        task_gen_id, 
        prices_db, 
        attempt=attempt, 
        timing_config=timing_config
    )

    # Добавляем nickname в результат
    return result, sid32_ret, sess_name, nickname

# ============================================================================
# ОСНОВНАЯ ФУНКЦИЯ ПАРСИНГА ИНВЕНТАРЯ
# ============================================================================

def task_steam_check(session, steam_id, task_gen_id, prices_db, attempt=0, timing_config=None):
    """
    Основная функция парсинга инвентаря Steam.
    Выполняет пагинацию, проверку приватности, подсчет стоимости предметов.

    Returns: (result_dict, sid32, session_name)
    """
    if session.mode != "steam":
        _trace(session.name, "Switching context: Translator -> Steam")
        session.restore_steam_context()

    if timing_config is None:
        timing_config = {}

    t_conn = timing_config.get("request_timeout_connect", 6.0)
    t_read = timing_config.get("request_timeout_read", 45.0)

    sess_obj = session.get_session()

    # --- Anti-Leak ---
    for forbidden in ["Authorization", "Origin", "X-Compress"]:
        if forbidden in sess_obj.headers:
            del sess_obj.headers[forbidden]

    steam_32 = to_steam_id32(steam_id)

    current_referer = f"https://steamcommunity.com/profiles/{steam_id}/inventory"

    _trace(session.name, f"--- START TASK for {steam_32}, Attempt {attempt} ---")

    # ========== 1. WARMUP / RECOVERY ==========
    try:
        current_cookies = sess_obj.cookies.get_dict()
        sessionid_exists = "sessionid" in current_cookies
        _trace(session.name, f"Cookie Check: sessionid present? {sessionid_exists}. Total cookies: {len(current_cookies)}")

        if not sessionid_exists:
            warmup_url = f"https://steamcommunity.com/profiles/{steam_id}/inventory"
            _trace(session.name, f"WARMUP INITIATED. Target: {warmup_url}")

            nav_headers = {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Referer": f"https://steamcommunity.com/profiles/{steam_id}",
                "Upgrade-Insecure-Requests": "1",
                "User-Agent": sess_obj.headers.get("User-Agent", "Mozilla/5.0")
            }

            _trace(session.name, f"Sending WARMUP GET request...")
            resp = sess_obj.get(warmup_url, headers=nav_headers, timeout=t_read, verify=False)
            current_referer = resp.url

            _trace(session.name, f"Warmup Response Code: {resp.status_code}. URL: {resp.url}")

            sess_obj.cookies.set("Steam_Language", "english", domain="steamcommunity.com")

            # Проверка приватности в HTML
            if ("profileprivateinfo" in resp.text) or ("This profile is private" in resp.text):
                _trace(session.name, "Profile detected as PRIVATE via HTML content.")
                logging.info(f"[{session.name}] Profile is PRIVATE (detected in HTML). Stopping.")
                return {
                    "success": True,
                    "price": 0,
                    "text": "Hidden",
                    "retry": False,
                    "latency": 0
                }, steam_32, session.name

            w_min = timing_config.get("warmup_delay_min", 2.0)
            w_max = timing_config.get("warmup_delay_max", 3.0)
            sleep_time = random.uniform(w_min, w_max)
            _trace(session.name, f"Warmup sleep for {sleep_time:.2f}s")
            time.sleep(sleep_time)

            if "sessionid" not in sess_obj.cookies.get_dict():
                _trace(session.name, "WARMUP FAILED: sessionid cookie missing after request.")
                logging.error(f"[{session.name}] WARMUP FAILED: No sessionid received.")
                return {
                    "success": False,
                    "price": 0,
                    "text": "Warmup Fail",
                    "retry": False,
                    "latency": 0
                }, steam_32, session.name
            else:
                _trace(session.name, "WARMUP SUCCESS: sessionid obtained.")

    except Exception as e:
        _trace(session.name, f"Warmup Exception: {e}")

        # Проверка на ошибку подключения к прокси
        if ("curl 97" in str(e)) or ("connection to proxy closed" in str(e)):
            session.reset_connection()
            return {
                "success": False,
                "price": 0,
                "text": "ProxyDrop",
                "retry": True,
                "latency": 0
            }, steam_32, session.name

    # ========== 2. ADAPTIVE PAGINATION ==========
    base_url = f"https://steamcommunity.com/inventory/{steam_id}/730/2"

    api_headers = {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": current_referer,
        "X-Requested-With": "XMLHttpRequest"
    }

    all_assets = []
    all_descriptions = {}
    start_assetid = None
    more_items = True
    page_count = 0

    start_ts = _get_time()
    result = {
        "success": False,
        "price": 0,
        "text": "",
        "retry": False,
        "latency": 0,
        "trigger_panic": False
    }

    _trace(session.name, "STARTING INVENTORY PAGINATION LOOP")

    try:
        while more_items:
            page_count += 1

            c_min = timing_config.get("request_count_min", 450)
            c_max = timing_config.get("request_count_max", 500)
            req_count = random.randint(c_min, c_max)

            params = {"l": "english", "count": str(req_count)}
            if start_assetid:
                params["start_assetid"] = start_assetid

            _trace(session.name, f"PAGE {page_count}: Preparing GET. Count={req_count}. StartAsset={start_assetid}")

            try:
                response = sess_obj.get(
                    base_url,
                    params=params,
                    headers=api_headers,
                    timeout=(t_conn, t_read),
                    verify=False
                )
            except Exception as req_err:
                err_msg = str(req_err)
                _trace(session.name, f"Network Error during GET: {err_msg}")

                # Проверка на ошибку 97
                if ("curl 97" in err_msg) or ("connection to proxy closed" in err_msg) or ("Connection reset" in err_msg):
                    logging.warning(f"[{session.name}] Proxy Connection Died (Error 97). Resetting session.")
                    session.reset_connection()
                    result["text"] = "ProxyReconn"
                    result["retry"] = True
                    return result, steam_32, session.name

                raise req_err

            status = response.status_code
            elapsed_req = response.elapsed.total_seconds() if response.elapsed else 0
            _trace(session.name, f"PAGE {page_count}: Response Recv. Status={status}. Time={elapsed_req:.3f}s. Size={len(response.content)} bytes.")

            # --- RATE LIMIT (429) ---
            if status == 429:
                _trace(session.name, f"!!! 429 RATE LIMIT DETECTED !!!")
                logging.warning(f"[{session.name}] 429 Rate Limit")
                result["retry"] = False
                result["trigger_panic"] = True
                result["text"] = "Rate Limit Drop"
                rl_wait = timing_config.get("rate_limit_cooldown", 60.0)
                session.mark_rate_limited(rl_wait)
                return result, steam_32, session.name

            # --- AUTH FAIL (401) ---
            if status == 401:
                _trace(session.name, f"!!! 401 AUTH FAIL !!! Clearing cookies.")
                session.delete_cookies()
                log_response_dump(response, steam_32, stage="SteamAPI_401", reason="AuthFail")
                result["retry"] = False
                result["text"] = "Retry (401) DROP"
                return result, steam_32, session.name

            # --- OTHER ERRORS ---
            if status != 200:
                _trace(session.name, f"Non-200 Status on Page {page_count}: {status}. Content: {response.text[:100]}...")
                log_response_dump(response, steam_32, stage=f"SteamAPI_{status}", reason="Error")

                if page_count == 1:
                    if status == 403:
                        result["text"] = "Hidden"
                        result["success"] = True
                        result["retry"] = False
                        session.record_success()
                    elif status == 400:
                        result["text"] = "BadReq (400)"
                        result["retry"] = False
                    else:
                        result["text"] = f"Http {status}"
                        result["retry"] = False
                    return result, steam_32, session.name
                else:
                    logging.warning(f"[{session.name}] Error on page {page_count}: {status}")
                    break

            # --- PARSING JSON ---
            try:
                json_data = response.json()
            except ValueError:
                _trace(session.name, f"FAILED to parse JSON. Raw body: {response.text[:50]}...")
                json_data = None

            if not json_data:
                _trace(session.name, "JSON is empty/invalid. Breaking loop.")
                break

            curr_assets = json_data.get("assets", [])
            curr_desc = json_data.get("descriptions", [])

            _trace(session.name, f"PAGE {page_count}: Parsed {len(curr_assets)} assets, {len(curr_desc)} descriptions.")

            if not curr_assets and page_count == 1:
                _trace(session.name, "First page has 0 assets. Inventory is Empty.")
                result["success"] = True
                result["text"] = "Empty"
                session.record_success()
                return result, steam_32, session.name

            all_assets.extend(curr_assets)
            for d in curr_desc:
                key = f"{d['classid']}_{d['instanceid']}"
                all_descriptions[key] = d

            more_items = json_data.get("more_items", False)
            start_assetid = json_data.get("last_assetid")

            _trace(session.name, f"PAGE {page_count}: Next? {more_items}. New Cursor: {start_assetid}")

            if more_items:
                p_min = timing_config.get("pagination_delay_min", 2.0)
                p_max = timing_config.get("pagination_delay_max", 3.5)
                delay = random.uniform(p_min, p_max)
                _trace(session.name, f"Sleeping {delay:.2f}s before next page...")
                time.sleep(delay)

            if page_count >= 50:
                _trace(session.name, "Page limit (50) reached. Force stopping.")
                logging.warning(f"[{session.name}] Page limit reached: {page_count}. Stopping.")
                break

        # ========== 3. CALCULATING PRICES ==========
        _trace(session.name, f"--- CALCULATING PRICES for {len(all_assets)} items ---")

        total_price = 0.0
        for asset in all_assets:
            key = f"{asset['classid']}_{asset['instanceid']}"
            if key in all_descriptions:
                d = all_descriptions[key]
                market_name = d.get("market_hash_name") or d.get("market_name")
                market_name = market_name.strip() if market_name else "Unknown"

                # Проверка marketable
                if d.get("marketable") != 1:
                    continue

                item_price = 0.0

                if prices_db:
                    # Прямой поиск
                    if market_name in prices_db:
                        item_data = prices_db[market_name]

                        if isinstance(item_data, dict):
                            item_price = item_data.get("suggested_price") or item_data.get("min_price") or 0
                            if DETAILED_ITEM_LOGGING and item_price > 0:
                                print(f"ITEM: {market_name} = {item_price}")
                        else:
                            # Skinport API format
                            item_price = float(item_data)
                            if DETAILED_ITEM_LOGGING and item_price > 0:
                                print(f"ITEM: {market_name} = {item_price} (old format)")
                    else:
                        # Поиск с очисткой имени
                        clean = clean_item_name(market_name)
                        if clean in prices_db:
                            item_data = prices_db[clean]
                            if isinstance(item_data, dict):
                                item_price = item_data.get("suggested_price") or item_data.get("min_price") or 0
                                if DETAILED_ITEM_LOGGING and item_price > 0:
                                    print(f"ITEM-CLEAN: {market_name} ({clean}) = {item_price}")
                            else:
                                item_price = float(item_data)
                                if DETAILED_ITEM_LOGGING and item_price > 0:
                                    print(f"ITEM-CLEAN: {market_name} ({clean}) = {item_price} (old format)")

                total_price += item_price

        duration = _get_time() - start_ts
        result["latency"] = duration
        result["success"] = True
        result["price"] = total_price
        result["text"] = f"OK ({len(all_assets)} itm)"

        _trace(session.name, f"Task Finished. Total Price: {total_price}. Latency: {duration:.2f}s")
        session.record_success()

    except Exception as e:
        # Проверка на ошибку 97 в outer loop
        if ("curl 97" in str(e)) or ("connection to proxy closed" in str(e)):
            logging.warning(f"[{session.name}] Caught Crash (97) in outer loop. Resetting.")
            session.reset_connection()
            result["text"] = "ProxyDrop Outer"
            result["retry"] = True
            return result, steam_32, session.name

        logging.error(f"[{session.name}] EXCEPTION: {e}")
        traceback.print_exc()
        result["text"] = "Err Crash"
        result["retry"] = False
        log_response_dump(None, steam_32, stage="SteamAPI_Crash", reason=str(e)[:50])

    return result, steam_32, session.name
