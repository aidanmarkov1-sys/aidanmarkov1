# --- START OF FILE network_debugger.py ---
import sys
import os
import json
import time
import socket
import subprocess
import datetime
import urllib.parse
import platform
import ssl
import logging
import traceback

# Импорт логгера из проекта
try:
    import logger
except ImportError:
    print("!!! CRITICAL: logger.py not found. Dumps will not be saved.")
    logger = None

from colorama import Fore, Style, init

# Инициализация цветов
init(autoreset=True)

CONFIG_FILE = 'config.json'
TARGET_URL = "https://prod-api.lzt.market/steam-value?link=test"
TARGET_HOST = "prod-api.lzt.market"

# --- LOGGING SETUP ---
def setup_verbose_logging():
    """Включает режим 'болтливости' для библиотек python"""
    print(f"{Fore.MAGENTA}[DEBUG] Enabling Low-Level Logging...{Style.RESET_ALL}")
    
    # Включаем логирование http.client (requests/urllib3 используют его)
    try:
        import http.client
        http.client.HTTPConnection.debuglevel = 1
    except: pass

    # Настраиваем logging
    logging.basicConfig()
    logging.getLogger().setLevel(logging.DEBUG)
    requests_log = logging.getLogger("urllib3")
    requests_log.setLevel(logging.DEBUG)
    requests_log.propagate = True

# --- UTILS ---
def print_header(text):
    print(f"\n{Fore.CYAN}{'='*15} {text} {'='*15}{Style.RESET_ALL}")

def print_step(text):
    print(f"\n{Fore.YELLOW}[STEP] {text}{Style.RESET_ALL}")

def print_ok(text):
    print(f"{Fore.GREEN}[OK] {text}{Style.RESET_ALL}")

def print_err(text):
    print(f"{Fore.RED}[ERR] {text}{Style.RESET_ALL}")

def print_info(text):
    print(f"{Fore.BLUE}[INFO] {text}{Style.RESET_ALL}")

def print_warn(text):
    print(f"{Fore.YELLOW}[WARN] {text}{Style.RESET_ALL}")

def load_config_raw():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f: return json.load(f)
        except: return {}
    return {}

# --- DIAGNOSTIC TOOLS ---

def check_active_interface():
    """Определяет, через какой интерфейс реально идет трафик"""
    print_step("Анализ активного сетевого интерфейса")
    try:
        # Создаем UDP сокет к Google DNS (соединения не происходит, но маршрут выбирается)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        print_info(f"Ваш локальный IP (Outbound): {Fore.WHITE}{local_ip}{Style.RESET_ALL}")
        
        # Пытаемся угадать имя адаптера (Windows)
        if os.name == 'nt':
            try:
                cmd = "ipconfig"
                res = subprocess.check_output(cmd, shell=True).decode('cp866', errors='ignore')
                if local_ip in res:
                    print_info("IP найден в выводе ipconfig. Проверьте, тот ли это адаптер (VPN/WiFi).")
                else:
                    print_err("ВНИМАНИЕ: Локальный IP не найден в ipconfig! Возможно, работает скрытый VPN/Proxy.")
            except: pass
    except Exception as e:
        print_err(f"Не удалось определить интерфейс: {e}")

def run_traceroute(target_host):
    """Запускает трассировку маршрута"""
    print_step(f"Запуск TraceRoute до {target_host}...")
    print_info("Это займет время (до 30 сек). Ждите...")
    
    cmd = ["tracert", "-d", target_host] if os.name == 'nt' else ["traceroute", "-n", target_host]
    
    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        print(f"{Fore.WHITE}", end="")
        full_output = ""
        while True:
            line = process.stdout.readline()
            if not line: break
            print(line.strip())
            full_output += line
        print(f"{Style.RESET_ALL}", end="")
        
        # Сохраняем дамп трассировки
        if logger:
            logger.save_crash_dump("TraceRoute", "System", 0, {}, full_output, reason="Trace Diagnost")
            
    except Exception as e:
        print_err(f"Ошибка трассировки: {e}")

def check_ssl_handshake_raw(host, port=443):
    """Пытается установить 'голое' SSL соединение без HTTP"""
    print_step(f"Raw SSL Handshake Test ({host}:{port})")
    
    context = ssl.create_default_context()
    try:
        s = socket.create_connection((host, port), timeout=5)
        with context.wrap_socket(s, server_hostname=host) as ssock:
            cipher = ssock.cipher()
            version = ssock.version()
            cert = ssock.getpeercert()
            
            print_ok(f"SSL Handshake: SUCCESS")
            print_info(f"Protocol: {version}")
            print_info(f"Cipher: {cipher[0]} ({cipher[2]} bits)")
            
            subject = dict(x[0] for x in cert['subject'])
            print_info(f"Cert Subject: {subject.get('commonName', 'Unknown')}")
            return True
    except ssl.SSLError as e:
        print_err(f"SSL ERROR: {e}")
        print_info("Сервер или Прокси отклонил шифрование. Возможно, проблема в DPI или MITM антивируса.")
        if logger: logger.save_crash_dump("SSL_Fail", host, 0, {}, str(e), reason="SSL Handshake Error")
        return False
    except Exception as e:
        print_err(f"Connection Error: {e}")
        return False

# --- DEEP LIBRARY TESTS WITH DUMPS ---

def test_libraries_with_dumps(proxy_str):
    print_header("БИБЛИОТЕЧНЫЕ ТЕСТЫ (С ДАМПАМИ)")
    
    # 1. Загрузка сертификатов (как в боте)
    cert_path = None
    try:
        import certifi
        cert_path = certifi.where()
    except: pass
    
    proxies = {"http": proxy_str, "https": proxy_str} if proxy_str else None
    
    # --- TEST 1: REQUESTS ---
    print_step("Test 1: Requests (Python Standard)")
    try:
        import requests
        print_info(f"Proxy: {proxies}")
        
        try:
            # Делаем запрос
            resp = requests.get(TARGET_URL, proxies=proxies, timeout=10, verify=cert_path)
            
            # Логируем успех
            print_ok(f"Status: {resp.status_code} | Size: {len(resp.content)} bytes")
            if logger: 
                logger.log_response_dump(resp, "Debugger_Requests", stage="Debug", reason="Success")
        
        except Exception as e:
            err_str = str(e)
            # Handle SOCKS missing dependency specifically
            if "Missing dependencies for SOCKS" in err_str or "InvalidSchema" in err_str and "socks" in err_str.lower():
                print(f"{Fore.YELLOW}[SKIP] Библиотека 'requests' пропущена (Нет SOCKS поддержки).{Style.RESET_ALL}")
                print_info("Это НОРМАЛЬНО. Основной бот использует curl_cffi, у которого поддержка встроена.")
            else:
                print_err(f"Requests Failed: {e}")
                # Логируем ошибку (дамп исключения)
                if logger:
                    logger.log_response_dump(None, "Debugger_Requests", stage="Debug", reason="Exception", exception_obj=e)

    except ImportError:
        print_err("Библиотека requests не установлена.")

    # --- TEST 2: CURL_CFFI ---
    print_step("Test 2: Curl_Cffi (Chrome 120 Impersonation)")
    try:
        from curl_cffi import requests as cffi
        
        # Настройки, имитирующие бота
        impersonate_ver = "chrome120"
        
        print_info(f"Impersonate: {impersonate_ver} | Certs: {cert_path}")
        
        try:
            sess = cffi.Session(impersonate=impersonate_ver)
            if proxies: sess.proxies = proxies
            
            # ВАЖНО: Если cert_path есть, используем его, иначе пробуем False (если была ошибка 77)
            verify_mode = cert_path if cert_path else True 
            
            resp = None
            
            # --- AUTO-FIX LOGIC FOR ERROR 77 ---
            try:
                # Первая попытка с проверкой сертификата
                resp = sess.get(TARGET_URL, timeout=15, verify=verify_mode)
            except Exception as e_inner:
                err_text = str(e_inner).lower()
                # Ловим Error 77 (проблема с чтением файла сертификатов, часто из-за кириллицы)
                if "error setting certificate" in err_text or "(77)" in err_text:
                    print_warn("Обнаружена ошибка Curl Error 77 (Проблема с путем к сертификатам).")
                    print_info(f"Вероятно, в пути к файлу '{cert_path}' есть кириллица.")
                    print_info("Автоматическое переключение на verify=False для теста...")
                    
                    # Повторная попытка без проверки
                    resp = sess.get(TARGET_URL, timeout=15, verify=False)
                else:
                    raise e_inner # Если ошибка другая, выбрасываем её дальше

            # Если дошли сюда, значит запрос (первый или повторный) прошел
            print_ok(f"Status: {resp.status_code} | Size: {len(resp.content)} bytes")
            if logger:
                logger.log_response_dump(resp, f"Debugger_Curl_{impersonate_ver}", stage="Debug", reason="Success")
                
        except Exception as e:
            err_msg = str(e)
            print_err(f"Curl Failed: {err_msg[:100]}...")
            
            if logger:
                logger.log_response_dump(None, f"Debugger_Curl_{impersonate_ver}", stage="Debug", reason="Crash", exception_obj=e)
                
            # Если ошибка 0 bytes, это важно выделить
            if "0 bytes" in err_msg or "empty reply" in err_msg:
                print(f"\n{Fore.RED}{Style.BRIGHT}!!! ОБНАРУЖЕНА ПРОБЛЕМА '0 BYTES' !!!{Style.RESET_ALL}")
                print_info("Смотрите дамп в папке logs/debug_dumps/ для деталей.")

    except ImportError:
        print_err("Библиотека curl_cffi не установлена.")


# --- MAIN MENU ---

def run_diagnostics():
    while True:
        os.system('cls' if os.name == 'nt' else 'clear')
        print(f"{Fore.CYAN}=== NETWORK FORENSICS v6.1 (AUTO-FIX) ==={Style.RESET_ALL}")
        
        cfg = load_config_raw()
        proxies = cfg.get('proxies', [])
        proxy_str = proxies[0] if proxies else None
        if proxy_str and "://" not in proxy_str: proxy_str = f"http://{proxy_str}"

        print(f"Target: {TARGET_HOST}")
        print(f"Proxy: {proxy_str if proxy_str else 'DIRECT (NO PROXY)'}")
        if logger: print(f"Logger: {Fore.GREEN}Active (Dumps Enabled){Style.RESET_ALL}")
        else: print(f"Logger: {Fore.RED}Inactive{Style.RESET_ALL}")

        print("\n1. ЗАПУСТИТЬ ПОЛНУЮ ДИАГНОСТИКУ (Trace, SSL, HTTP Dumps)")
        print("2. Включить VERBOSE-режим (Много текста в консоль)")
        print("0. Выход")
        
        choice = input(f"\n{Fore.WHITE}Ваш выбор: {Style.RESET_ALL}")
        
        if choice == '1':
            print_header("ЗАПУСК ПОЛНОЙ ДИАГНОСТИКИ")
            
            # 1. Интерфейс
            check_active_interface()
            
            # 2. Трассировка (без прокси, чтобы проверить локаль)
            run_traceroute(TARGET_HOST)
            
            # 3. SSL Handshake (прямой тест сервера)
            check_ssl_handshake_raw(TARGET_HOST)
            
            # 4. Библиотеки + Дампы
            if proxy_str:
                test_libraries_with_dumps(proxy_str)
            else:
                print_warn("Прокси не задан! Тестируем прямое соединение...")
                test_libraries_with_dumps(None)
                
            print_header("ДИАГНОСТИКА ЗАВЕРШЕНА")
            print_info(f"Проверьте папку {Fore.YELLOW}logs/debug_dumps/{Style.RESET_ALL} на наличие JSON-файлов.")
            input("\nНажмите Enter...")
            
        elif choice == '2':
            setup_verbose_logging()
            print_ok("Режим Verbose включен. Теперь запустите диагностику (1).")
            time.sleep(1)
            
        elif choice == '0':
            break

if __name__ == "__main__":
    run_diagnostics()