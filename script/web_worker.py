import threading
import time
import queue
import random
import ctypes
import os
import json
import pickle
import re
import html
import logging
from concurrent.futures import ThreadPoolExecutor
from colorama import Fore, Style
from datetime import datetime

# Импортируем модули проекта
import logger
import web_worker_threads as threads
import log_parser

# --- CONFIG & PATHS ---
COOKIES_DIR = "cookies"
if not os.path.exists(COOKIES_DIR): os.makedirs(COOKIES_DIR)

SCORES_FILE = "proxy_stats.json"
PRICES_FILE = "dota2_items_list.json"

try:
    import certifi
    SAFE_CERT_PATH = certifi.where()
except: pass

try:
    import requests as std_requests
except ImportError:
    std_requests = None

try:
    from curl_cffi import requests
    CURL_AVAILABLE = True
    STABLE_IMPERSONATE = "chrome120"
except ImportError:
    import requests
    CURL_AVAILABLE = False

# --- PROXY SCORE MANAGER ---
class ProxyScoreManager:
    def __init__(self):
        self.lock = threading.Lock()
        self.stats = {}
        self._load()

    def _load(self):
        if os.path.exists(SCORES_FILE):
            try:
                with open(SCORES_FILE, 'r') as f:
                    self.stats = json.load(f)
            except: pass

    def _save(self):
        try:
            with open(SCORES_FILE, 'w') as f: json.dump(self.stats, f)
        except: pass

    def record_success(self, proxy_url):
        key = proxy_url if proxy_url else "LOCAL"
        with self.lock:
            if key not in self.stats: self.stats[key] = {"s": 0, "f": 0}
            self.stats[key]["s"] += 1
        self._save()

    def record_fail(self, proxy_url):
        key = proxy_url if proxy_url else "LOCAL"
        with self.lock:
            if key not in self.stats: self.stats[key] = {"s": 0, "f": 0}
            self.stats[key]["f"] += 1
        self._save()

    def get_score(self, proxy_url):
        key = proxy_url if proxy_url else "LOCAL"
        data = self.stats.get(key)
        if not data: return 1.0
        s = data.get("s", 0)
        f = data.get("f", 0)
        total = s + f
        if total == 0: return 1.0
        ratio = s / total
        return round(ratio * 2.0, 3)

    def sort_proxies(self, proxy_list):
        if not proxy_list: return []
        return sorted(proxy_list, key=lambda p: self.get_score(p), reverse=True)

score_manager = ProxyScoreManager()

# --- NICKNAME RESOLVER ---
class NicknameResolver:
    def __init__(self, cache_ref, proxy_list_raw, worker_ref, max_threads=2):
        self.cache = cache_ref
        self.worker_ref = worker_ref
        self.executor = ThreadPoolExecutor(max_workers=max_threads, thread_name_prefix="NickMiner")
        self.session = requests.Session()
        if CURL_AVAILABLE:
            self.session = requests.Session(impersonate="chrome110")
        
        if proxy_list_raw:
            p = random.choice(proxy_list_raw)
            p = f"http://{p}" if "://" not in p else p
            self.session.proxies = {"http": p, "https": p}

    def add_task(self, steam_id, ignore_cache=False):
        """
        Добавляет задачу на получение ника.
        :param ignore_cache: Если True, не проверяет наличие записи в log_parser (история сканирований).
        """
        if steam_id not in self.cache:
            self.executor.submit(self._fetch_nick, steam_id, ignore_cache)

    def _fetch_nick(self, steam_id, ignore_cache):
        if steam_id in self.cache: return
        try:
            url = f"https://steamcommunity.com/profiles/{steam_id}/?xml=1"
            resp = self.session.get(url, timeout=5, verify=False)
            if resp.status_code == 200:
                match = re.search(r'<steamID><!\[CDATA\[(.*?)\]\]></steamID>', resp.text)
                if match:
                    nick = html.unescape(match.group(1))
                    self.cache[steam_id] = nick
                    
                    # Проверяем историю (кэш логов) только если не установлен флаг ignore_cache
                    if log_parser.parser_instance and not ignore_cache:
                        entry = log_parser.parser_instance.find_entry(nick)
                        if entry:
                            price, currency, date_obj = entry
                            days = (datetime.now() - date_obj).days
                            
                            # Помечаем как обработанный, чтобы не сканировать снова
                            self.worker_ref.cancelled_ids.add(steam_id)
                            sid32 = threads.to_steam_id32(str(steam_id))
                            self.worker_ref.completed_ids.add(steam_id)
                            self.worker_ref.completed_ids.add(sid32)
                            
                            msg = f"{Fore.CYAN}[CACHE]{Style.RESET_ALL} {nick} | {Fore.GREEN}{price} {currency}{Style.RESET_ALL} | LC ({days}дн. назад)"
                            logger.log_worker(msg)
                            
                            if self.worker_ref.overlay_queue:
                                disp_txt = f"{nick}: {price} {currency} (LC {days}д.)"
                                self.worker_ref.overlay_queue.put({
                                    'text': disp_txt,
                                    'price': price,
                                    'type': 'price'
                                })
        except: pass

    def stop(self):
        self.executor.shutdown(wait=False)

# --- STICKY SESSION ---
class StickySession:
    def __init__(self, token=None, proxy_url=None, name="Session", config=None):
        self.token = token
        self.proxy_url = proxy_url
        self.name = name
        self.config = config or {}
        
        clean_name = "".join(x for x in name if x.isalnum() or x in "-_")
        self.cookie_file = os.path.join(COOKIES_DIR, f"{clean_name}.pkl")
        
        self.is_alive = True
        self.rate_limited_until = 0
        self.next_available_time = 0 
        self.active_requests = 0
        self.latency = 0.5
        self.consecutive_timeouts = 0
        self.last_usage = 0 
        self.mode = "steam"
        self.keep_role_until = 0
        self._saved_steam_cookies = {}
        self.proxy_dict = {"http": proxy_url, "https": proxy_url} if proxy_url else None
        self._session = None
        self._init_session()

    def _init_session(self):
        if self._session:
            try: self._session.close()
            except: pass
        if CURL_AVAILABLE:
            self._session = requests.Session(impersonate=STABLE_IMPERSONATE)
        else:
            self._session = requests.Session()
            self._session.headers.update({"User-Agent": "Mozilla/5.0..."})
        if self.proxy_dict: self._session.proxies = self.proxy_dict.copy()
        self.restore_steam_context()

    def reset_connection(self):
        """Полный сброс TCP-соединения (лечит ошибку 97/Connection Closed)"""
        try:
            self._session.close()
        except: pass
        self._init_session()

    def update_latency(self, val):
        self.latency = (self.latency * 0.7) + (val * 0.3)
    
    def record_success(self):
        score_manager.record_success(self.proxy_url)
        self.consecutive_timeouts = 0

    def record_fail(self):
        score_manager.record_fail(self.proxy_url)

    def report_timeout(self):
        self.consecutive_timeouts += 1

    @property
    def score(self):
        return score_manager.get_score(self.proxy_url)

    def switch_to_translator(self):
        try:
            self._saved_steam_cookies = self._session.cookies.get_dict()
            self._session.cookies.clear()
            self.mode = "translator"
            return True
        except: return False

    def restore_steam_context(self):
        try:
            self.mode = "steam"
            self._session.cookies.clear()
            
            # Пытаемся восстановить куки
            if self._saved_steam_cookies:
                self._session.cookies.update(self._saved_steam_cookies)
            else:
                self._load_cookies_from_file()
            
            # Чистим заголовки
            keys_to_remove = ["Authorization", "Origin", "X-Compress"]
            for k in keys_to_remove:
                if k in self._session.headers:
                    del self._session.headers[k]

            auth_headers = {
                "Referer": "https://steamcommunity.com/",
            }
            self._session.headers.update(auth_headers)
        except: pass

    def _load_cookies_from_file(self):
        if os.path.exists(self.cookie_file):
            try:
                with open(self.cookie_file, 'rb') as f:
                    d = pickle.load(f)
                    self._session.cookies.update(d)
            except: pass

    def save_cookies(self):
        if self.mode == "steam":
            try:
                d = self._session.cookies.get_dict()
                if not d: return
                with open(self.cookie_file, 'wb') as f: pickle.dump(d, f)
            except Exception as e:
                logger.log_worker(f"{Fore.RED}[{self.name}] ERROR saving cookies: {e}{Style.RESET_ALL}")

    def delete_cookies(self):
        try:
            self._session.cookies.clear()
            self._saved_steam_cookies = {}
            if os.path.exists(self.cookie_file):
                os.remove(self.cookie_file)
        except: pass

    def get_session(self): return self._session

    def set_cooldown(self, seconds):
        self.next_available_time = time.time() + seconds

    def is_ready(self):
        if time.time() < self.rate_limited_until: return False
        if time.time() < self.next_available_time: return False
        if not self.is_alive: return False
        if self.active_requests > 0: return False
        return True

    def mark_rate_limited(self, dur=None):
        if dur is None:
            dur = self.config.get("rate_limit_cooldown", 60)
        self.rate_limited_until = time.time() + dur

# --- WEB WORKER MANAGER ---
class WebWorker:
    def __init__(self):
        self.queue = queue.Queue()      
        self.retry_queue = queue.Queue() 
        self.translation_queue = queue.Queue()
        
        self.running = False
        self.sessions = []
        self.settings = {} 

        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="Exec")
        self.nickname_cache = {}
        self.nick_resolver = None
        self.current_generation = 0
        self.gen_lock = threading.Lock()
        self.overlay_queue = None
        
        self.panic_until = 0 
        self.completed_ids = set()
        self.cancelled_ids = set()

        self.prices_db = {}
        self._load_prices()

    def _update_prices_from_api(self):
        """Загружает цены CS:GO с Skinport API (БЕЗ КЛЮЧА)"""
        logger.log_worker(f"{Fore.CYAN}[Updater] Downloading CS:GO prices from Skinport API...{Style.RESET_ALL}")

        try:
            url = "https://api.skinport.com/v1/items?app_id=730&currency=USD"
            req_lib = std_requests if std_requests else requests

            response = req_lib.get(url, timeout=60)

            if response.status_code != 200:
                logger.log_worker(f"{Fore.RED}[Updater] API Error: HTTP {response.status_code}{Style.RESET_ALL}")
                return False

            raw_items = response.json()

            if not isinstance(raw_items, list):
                logger.log_worker(f"{Fore.RED}[Updater] Unexpected response format{Style.RESET_ALL}")
                return False

            # Сохраняем в СЫРОМ формате
            with open(PRICES_FILE, 'w', encoding='utf-8') as f:
                json.dump(raw_items, f, ensure_ascii=False, indent=2)

            logger.log_worker(f"{Fore.GREEN}[Updater] Success! Saved {len(raw_items)} CS:GO items (Skinport).{Style.RESET_ALL}")
            return True

        except Exception as e:
            logger.log_worker(f"{Fore.RED}[Updater] Failed: {e}{Style.RESET_ALL}")
            return False

    def _load_prices(self):
        should_update = False
        if not os.path.exists(PRICES_FILE):
            logger.log_worker(f"{Fore.YELLOW}[Init] Prices file not found. Attempting download...{Style.RESET_ALL}")
            should_update = True
        else:
            file_time = os.path.getmtime(PRICES_FILE)
            age_seconds = time.time() - file_time
            if age_seconds > 86400:
                logger.log_worker(f"{Fore.YELLOW}[Init] Prices file is old. Updating...{Style.RESET_ALL}")
                should_update = True
        
        if should_update:
            self._update_prices_from_api()

        if os.path.exists(PRICES_FILE):
            try:
                with open(PRICES_FILE, 'r', encoding='utf-8') as f:
                    raw_data = json.load(f)
                
                if isinstance(raw_data, list):
                    self.prices_db = {}
                    for item in raw_data:
                        if isinstance(item, dict):
                            p_name = item.get("name")
                            p_val = item.get("price")
                            if p_name and p_val is not None:
                                self.prices_db[p_name] = float(p_val)
                elif isinstance(raw_data, dict):
                    self.prices_db = raw_data
                logger.log_worker(f"{Fore.GREEN}[Init] Loaded {len(self.prices_db)} prices for Dota 2.{Style.RESET_ALL}")
            except Exception as e:
                logger.log_error(f"Failed to load prices: {e}")

    def set_api_token(self, token_data, proxy_list_raw=None, overlay_queue=None, worker_timing_settings=None):
        self.overlay_queue = overlay_queue
        self.sessions = []
        
        try:
            if os.path.exists("config.json"):
                with open("config.json", 'r', encoding='utf-8') as f:
                    full_cfg = json.load(f)
                    self.settings = full_cfg.get("web_worker_timing", {})
            
            if not self.settings:
                logger.log_worker(f"{Fore.RED}[CRITICAL] 'web_worker_timing' not found in config.json!{Style.RESET_ALL}")
                return
        except Exception as e:
            logger.log_worker(f"{Fore.RED}[Config] CRITICAL error reading config: {e}{Style.RESET_ALL}")
            return

        max_workers = self.settings["max_concurrent_workers"]
        miner_workers = self.settings["max_miner_workers"]
        
        if self.executor._max_workers != max_workers:
            self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="Exec")

        self.nick_resolver = NicknameResolver(self.nickname_cache, proxy_list_raw, self, max_threads=miner_workers)

        sorted_proxies = []
        if proxy_list_raw:
            clean_proxies = [p.strip() for p in proxy_list_raw if p.strip()]
            clean_proxies = [f"http://{p}" if "://" not in p else p for p in clean_proxies]
            sorted_proxies = score_manager.sort_proxies(clean_proxies)

        tokens = [t for t in token_data if len(str(t)) > 5] if isinstance(token_data, list) else [token_data]
        if not tokens: tokens = ["GenericToken"]

        count = max(len(sorted_proxies) if sorted_proxies else 1, len(tokens))
        
        for i in range(count):
            proxy = sorted_proxies[i % len(sorted_proxies)] if sorted_proxies else None
            token = tokens[i % len(tokens)]
            short_proxy_name = "Local"
            if proxy:
                ip_match = re.search(r'(\d{1,3})\.\d{1,3}\.\d{1,3}\.(\d{1,3})', proxy)
                short_proxy_name = f"{ip_match.group(1)}...{ip_match.group(2)}" if ip_match else proxy[-10:]

            worker_ui_name = f"Worker-{i+1} [{short_proxy_name}]"
            s = StickySession(token, proxy, name=worker_ui_name, config=self.settings)
            self.sessions.append(s)

    def add_steam_id(self, steam_id, ignore_cache=False):
        """
        Добавляет задачу на сканирование SteamID.
        :param ignore_cache: Если True, игнорирует проверку по локальной истории (log_parser),
                             заставляя воркер сканировать инвентарь заново.
        """
        with self.gen_lock:
            sid_str = str(steam_id)
            if self.nick_resolver: 
                # Передаем параметр ignore_cache в резолвер
                self.nick_resolver.add_task(sid_str, ignore_cache=ignore_cache)
            
            sid32 = threads.to_steam_id32(sid_str)
            nick = self.nickname_cache.get(sid_str, sid32)
            if self.overlay_queue:
                 self.overlay_queue.put({'type': 'scanning', 'text': f"{nick}: Сканируется...", 'price': 0})
            self.queue.put((sid_str, self.current_generation, 0))

    def add_translation_task(self, mode_flag=None):
        self.translation_queue.put(mode_flag)

    def clear_queue(self):
        with self.gen_lock: self.current_generation += 1
        for q in [self.queue, self.retry_queue]:
            while not q.empty():
                try: q.get_nowait()
                except: pass
        self.panic_until = 0
        self.completed_ids.clear()
        self.cancelled_ids.clear()
        logger.log_worker(f"{Fore.GREEN}All Queues Flushed & Panic Reset!{Style.RESET_ALL}")

    def start(self):
        if self.running: return
        self.running = True
        threading.Thread(target=self._dispatcher, daemon=True, name="Brain").start()
        threading.Thread(target=self._pinger, daemon=True, name="Pinger").start()

    def stop(self):
        self.running = False
        self.executor.shutdown(wait=False)
        if self.nick_resolver: self.nick_resolver.stop()

    def _pinger(self):
        while self.running:
            time.sleep(5) 
            if self.queue.qsize() > 5: continue
            now = time.time()
            for s in self.sessions:
                if not s.is_ready(): continue
                if s.active_requests > 0: continue
                if s.mode == "translator" and now < s.keep_role_until: continue
                if random.random() < 0.15:
                    s.active_requests += 1
                    self.executor.submit(self._wrap_ping, s)

    def _wrap_ping(self, session):
        try: threads.task_ping(session)
        finally: 
            session.set_cooldown(1.0)
            session.active_requests -= 1

    def _dispatcher(self):
        while self.running:
            try:
                if time.time() < self.panic_until:
                    time.sleep(0.1)
                    continue

                if not self.translation_queue.empty():
                    self._handle_translation()
                    continue

                task_data = None
                try:
                    task_data_retry = self.retry_queue.get_nowait()
                    sid, gen, att, start_t, exec_at = task_data_retry
                    
                    if time.time() < exec_at:
                        self.retry_queue.put(task_data_retry)
                    elif time.time() - start_t > self.settings["request_timeout_read"] + 15:
                        if self.overlay_queue:
                            nick = self.nickname_cache.get(sid, sid)
                            self.overlay_queue.put({'type': 'not_found', 'text': f"{nick}: Timeout", 'price': 0})
                    elif sid in self.completed_ids:
                        pass 
                    else:
                        task_data = (sid, gen, att, start_t)
                except queue.Empty:
                    pass

                if not task_data:
                    try:
                        task_data_new = self.queue.get_nowait()
                        sid, gen, att = task_data_new
                        task_data = (sid, gen, att, time.time())
                    except queue.Empty:
                        pass

                if not task_data:
                    time.sleep(self.settings.get("queue_empty_sleep", 1))
                    continue

                sid, gen, att, start_t = task_data
                with self.gen_lock:
                    if gen != self.current_generation: continue

                candidates = [s for s in self.sessions if s.is_ready()]
                
                if not candidates:
                    sleep_val = self.settings.get("no_session_sleep", 2)
                    time.sleep(sleep_val)
                    self.retry_queue.put((sid, gen, att, start_t, time.time() + 1))
                    continue

                candidates.sort(key=lambda s: (-s.score, s.last_usage))
                chosen = candidates[0]
                
                if chosen.mode == "translator" and time.time() < chosen.keep_role_until:
                    alts = [c for c in candidates if c.mode == "steam"]
                    if alts: chosen = alts[0]

                chosen.active_requests += 1
                chosen.last_usage = time.time() 
                self.executor.submit(self._wrap_steam_check, chosen, sid, gen, att, start_t)
                
                d_min = self.settings.get("dispatcher_delay_min", 4.5)
                d_max = self.settings.get("dispatcher_delay_max", 5.0)
                time.sleep(random.uniform(d_min, d_max))

            except Exception as e:
                logger.log_error(f"Disp Error: {e}")
                err_sleep = self.settings.get("on_error_retry_delay", 1)
                time.sleep(err_sleep)

    def _handle_translation(self):
        try: mode_flag = self.translation_queue.get_nowait()
        except: return
        candidates = [s for s in self.sessions if s.is_ready()]
        if not candidates:
            if self.overlay_queue: self.overlay_queue.put({'type': 'translation', 'text': 'No Workers!', 'price': 0})
            return
        translators = [s for s in candidates if s.mode == "translator"]
        chosen = translators[0] if translators else candidates[0]
        if self.overlay_queue: self.overlay_queue.put({'type': 'translation', 'text': 'Translating...', 'price': 0})
        chosen.active_requests += 1
        self.executor.submit(self._wrap_translation, chosen, mode_flag)

    def _wrap_steam_check(self, session, steam_id, gen, attempt, start_time):
        try:
            if steam_id in self.cancelled_ids:
                return

            res, sid32, w_name = threads.task_steam_check(session, steam_id, gen, self.prices_db, attempt=attempt, timing_config=self.settings)
            nick = self.nickname_cache.get(steam_id, sid32)
            
            if "Retry (401)" in res["text"] or "AuthFail" in res["text"]:
                session.delete_cookies()

            if res.get("trigger_panic"):
                wait_time = self.settings["rate_limit_cooldown"]
                full_proxy = session.proxy_dict.get('http', 'Local') if session.proxy_dict else 'Local'
                
                logger.log_worker(f"{Fore.YELLOW}[WARNING] [{w_name}] ({full_proxy}){Style.RESET_ALL} {nick}: Rate Limit (429). Wait {wait_time}s...")
                
                if self.overlay_queue:
                    self.overlay_queue.put({'type': 'panic', 'text': f'{nick}: Rate Limit (Wait...)', 'price': 0})
                
                if res.get("retry", True):
                    self.retry_queue.put((steam_id, gen, attempt + 1, start_time, time.time() + wait_time)) 
                return

            with self.gen_lock:
                if gen != self.current_generation: return

            if res["success"]:
                if steam_id in self.completed_ids: return
                self.completed_ids.add(steam_id)
                self.completed_ids.add(sid32)
                session.save_cookies()
                
                price = res["price"]
                txt = res["text"]
                col = Fore.GREEN if res["latency"] < 3 else Fore.YELLOW
                p_col = Fore.MAGENTA if price > 1000 else Fore.GREEN
                full_proxy = session.proxy_dict.get('http', 'Local') if session.proxy_dict else 'Local'
                
                msg = f"{Fore.BLUE}[{w_name}]{Style.RESET_ALL} {nick} | {p_col}{int(price)} ₽{Style.RESET_ALL} | {txt} | {col}{res['latency']:.2f}s{Style.RESET_ALL} | {Fore.BLACK}{Style.BRIGHT}{full_proxy}{Style.RESET_ALL}"
                logger.log_worker(msg)
                
                if self.overlay_queue:
                    disp_txt = f"{nick}: [СКРЫТ]" if "Hidden" in txt else f"{nick}: {int(price)} ₽"
                    self.overlay_queue.put({'text': disp_txt, 'price': price, 'type': 'price'})
                return

            r1 = self.settings["retry_delay_first"]
            r2 = self.settings["retry_delay_second"]
            timeout = self.settings["request_timeout_read"]

            if res.get("retry_later"):
                 self.retry_queue.put((steam_id, gen, attempt + 1, start_time, time.time() + r2))
                 return

            if res["retry"] and attempt < 2:
                self.retry_queue.put((steam_id, gen, attempt + 1, start_time, time.time() + r1))
                return

            if res["retry"] and time.time() - start_time < timeout:
                 self.retry_queue.put((steam_id, gen, attempt + 1, start_time, time.time() + r2))
                 return

            if steam_id not in self.completed_ids:
                full_proxy = session.proxy_dict.get('http', 'Local') if session.proxy_dict else 'Local'
                logger.log_worker(f"{Fore.RED}[{w_name}] ({full_proxy}) FAILED: {res['text']} ({nick}){Style.RESET_ALL}", level="ERROR")
                if self.overlay_queue:
                    self.overlay_queue.put({'type': 'not_found', 'text': f"{nick}: Ошибка", 'price': 0})

        except Exception as e:
            logger.log_error(f"Wrapper Crash: {e}")
        finally:
            t_min = self.settings.get("task_delay_min", 2.0)
            t_max = self.settings.get("task_delay_max", 3.0)
            if t_max <= 0: t_max = 0.5
            if t_min > t_max: t_min = t_max
            cooldown = random.uniform(t_min, t_max)
            session.set_cooldown(cooldown)
            session.active_requests -= 1

    def _wrap_translation(self, session, mode_flag=None):
        try:
            res = threads.task_translation(session, text_dummy=mode_flag)
            if self.overlay_queue:
                self.overlay_queue.put({'type': 'translation', 'text': res["text"], 'price': 0})
        except Exception as e:
            logger.log_error(f"Wrapper Translation Error: {e}")
        finally:
            session.set_cooldown(1.0)
            session.active_requests -= 1

worker_instance = WebWorker()