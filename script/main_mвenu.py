import os
import sys
import time
import threading
import traceback
import keyboard 
import ctypes
import queue
import ui 
from config_utils import load_config, save_config 
from settings_menu import edit_settings 

# --- IMPORT BLOCK ---
try:
    from stop import state_manager
    from core import main_cycle, run_ocr_cycle, run_mixed_cycle
except ImportError as e:
    print(f"{ui.Gradient.RED}Ошибка импорта core/stop: {e}")
    sys.exit(1)

try:
    import ocr_scanner
except Exception: ocr_scanner = None

try:
    from overlay import OverlayController
except ImportError:
    OverlayController = None
    print(f"{ui.Gradient.YELLOW}[Warning] overlay.py не найден. Оверлей будет отключен.")

try:
    from web_worker import worker_instance, score_manager
    from actions import perform_quick_scan
except ImportError as e:
    print(f"{ui.Gradient.RED}Ошибка импорта web_worker/actions: {e}")
    worker_instance = None
    score_manager = None
    perform_quick_scan = None

try:
    import network_debugger
except ImportError:
    network_debugger = None

try:
    from translator import translator_instance
except ImportError:
    translator_instance = None
    print(f"{ui.Gradient.YELLOW}[Warning] translator.py не найден. Переводчик отключен.")

# --- MANUAL INPUT IMPORT ---
try:
    import manual_input
except ImportError:
    manual_input = None
    print(f"{ui.Gradient.YELLOW}[Warning] manual_input.py не найден.")

# --- LOG PARSER IMPORT ---
try:
    import log_parser
except ImportError:
    log_parser = None
    print(f"{ui.Gradient.YELLOW}[Warning] log_parser.py не найден. Сбор статистики отключен.")

overlay_thread = None

def cleanup_resources():
    global overlay_thread
    if worker_instance:
        try: worker_instance.stop()
        except: pass
    
    if overlay_thread:
        try: overlay_thread.stop()
        except: pass

    # Stop log parser
    if log_parser:
        try: log_parser.stop_parser()
        except: pass
    
    try: keyboard.unhook_all()
    except: pass

def win_handler(ctrl_type):
    cleanup_resources()
    return True 

if os.name == 'nt':
    PHANDLER_ROUTINE = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_uint)
    handler = PHANDLER_ROUTINE(win_handler)
    ctypes.windll.kernel32.SetConsoleCtrlHandler(handler, True)

def select_profile():
    profiles_dir = 'profiles'
    if not os.path.exists(profiles_dir): os.makedirs(profiles_dir)
    if not os.listdir(profiles_dir): print(f"{ui.Gradient.RED}Папка 'profiles' пуста."); time.sleep(2); return None
    profiles = [f for f in os.listdir(profiles_dir) if f.endswith('.json')]
    while True:
        ui.clear_console() 
        print("\n" + ui.Gradient.YELLOW + "--- Выбор профиля ---")
        for i, profile in enumerate(profiles, 1): print(f"{ui.Gradient.MEDIUM_CYAN}{i}. {profile}")
        print(f"{ui.Gradient.RED}0. Назад")
        try:
            choice = input(ui.Gradient.WHITE + "Выберите профиль: ")
            if choice == '0': return None 
            choice_num = int(choice)
            if 1 <= choice_num <= len(profiles): return os.path.join(profiles_dir, profiles[choice_num - 1])
        except ValueError: pass

def network_monitor_loop():
    """Interactive Network Monitor"""
    if not worker_instance:
        print(f"{ui.Gradient.RED}Воркер не инициализирован. Запустите бота хотя бы раз или проверьте конфиг.")
        time.sleep(2)
        return

    def mask_proxy(proxy_str):
        if not proxy_str: return "Direct (Local)"
        if "@" in proxy_str: return proxy_str.split("@")[-1]
        return proxy_str

    cfg = load_config()
    key_main = cfg.get('hotkeys', {}).get('translator_key', 'F7').upper()
    key_sec = cfg.get('hotkeys', {}).get('secondary_translator_key', 'F8').upper()

    while True:
        ui.clear_console()
        print(f"{ui.Gradient.CYAN}=== МОНИТОР СЕТИ ===")
        
        # --- TABLE 1: WORKERS ---
        print(f"{ui.Gradient.WHITE}АКТИВНЫЕ СЕССИИ (Воркеры): {len(worker_instance.sessions)}")
        print("-" * 105)
        header = f"{'SESSION NAME':<18} | {'MODE':<10} | {'PROXY':<20} | {'SCORE':<5} | {'PING':<6} | {'STATUS'}"
        print(f"{ui.Gradient.YELLOW}{header}")
        print("-" * 105)

        if not worker_instance.sessions:
            print(f"{ui.Gradient.RED}Нет сессий. Проверьте lzt_api_token.")

        for s in worker_instance.sessions:
            status_color = ui.Gradient.GREEN
            status_txt = "OK"
            
            if not s.is_alive:
                status_color = ui.Gradient.RED
                status_txt = "DEAD"
            elif time.time() < s.rate_limited_until:
                status_color = ui.Gradient.YELLOW
                status_txt = f"LIMIT {int(s.rate_limited_until - time.time())}s"
            elif s.consecutive_timeouts > 0:
                status_color = ui.Gradient.YELLOW
                status_txt = f"T/O {s.consecutive_timeouts}"

            p_url = mask_proxy(s.proxy_url)
            p_score = 0
            score_col = ui.Gradient.WHITE
            if s.proxy_url and score_manager:
                p_score = score_manager.get_score(s.proxy_url)
                if p_score < 0: score_col = ui.Gradient.RED
                elif p_score > 10: score_col = ui.Gradient.GREEN
            
            lat = f"{s.latency:.2f}s"
            ping_col = ui.Gradient.GREEN if s.latency < 2.0 else ui.Gradient.YELLOW
            real_mode = "LZT" if s.mode == "steam" else "TRANS"
            mode_col = ui.Gradient.CYAN if s.mode == "steam" else ui.Gradient.MAGENTA

            row = f"{s.name:<18} | {mode_col}{real_mode:<10}{ui.Gradient.WHITE} | {p_url:<20} | {score_col}{p_score:<5}{ui.Gradient.WHITE} | {ping_col}{lat:<6}{ui.Gradient.WHITE} | {status_color}{status_txt}"
            print(row + ui.Gradient.RESET)

        print("-" * 105)
        
        # --- TABLE 2: AUX SERVICES ---
        print(f"\n{ui.Gradient.WHITE}ВСПОМОГАТЕЛЬНЫЕ СЕРВИСЫ:")
        print("-" * 60)
        print(f"{ui.Gradient.YELLOW}{'SERVICE':<20} | {'STATUS':<15} | {'INFO'}")
        print("-" * 60)

        nick_status = f"{ui.Gradient.RED}NOT INIT"
        nick_info = ""
        if worker_instance.nick_resolver:
            nick_status = f"{ui.Gradient.GREEN}ACTIVE"
            nick_info = f"Cache: {len(worker_instance.nickname_cache)}"
        print(f"Nick Resolver        | {nick_status}{ui.Gradient.WHITE} | {nick_info}")

        trans_status = f"{ui.Gradient.RED}NOT INIT"
        trans_info = "Check Config"
        if translator_instance:
            if translator_instance.is_ready:
                trans_status = f"{ui.Gradient.GREEN}READY"
                trans_info = f"{key_main}=Main, {key_sec}=Sec Area"
            else:
                trans_status = f"{ui.Gradient.RED}ERROR"
                trans_info = "Proxy/Key Fail"
        else:
            trans_info = "Module Missing"
            
        print(f"Groq Translator      | {trans_status}{ui.Gradient.WHITE}      | {trans_info}")
        
        # Log Parser Info
        parser_status = f"{ui.Gradient.RED}OFF"
        parser_info = "Module Missing"
        if log_parser:
            if log_parser.parser_instance and log_parser.parser_instance.is_alive():
                parser_status = f"{ui.Gradient.GREEN}RUNNING"
                cache_size = len(log_parser.parser_instance.cache['entries'])
                parser_info = f"Entries: {cache_size}"
            else:
                parser_info = "Stopped"
        print(f"Log Parser           | {parser_status}{ui.Gradient.WHITE}      | {parser_info}")

        print("-" * 60)

        print(f"\n{ui.Gradient.WHITE}Queues: Main={worker_instance.queue.qsize()} | Retry/API={worker_instance.retry_queue.qsize()}")
        
        print(f"\n{ui.Gradient.CYAN}[1/Enter] Обновить   [2] DEEP DEBUG (Анализ проблем)   [0] Назад в меню")
        choice = input(f"{ui.Gradient.WHITE}>> ")

        if choice == '0':
            break
        elif choice == '2':
            if network_debugger:
                ui.clear_console()
                network_debugger.run_diagnostics()
            else:
                print(f"{ui.Gradient.RED}Модуль network_debugger.py не найден!")
                time.sleep(2)

def run_bot_loop(selected_profile=None, mode="CLASSIC"):
    config = load_config()
    hotkey = config.get('hotkeys', {}).get('start_stop_key', 'F6').upper()
    scan_key = config.get('hotkeys', {}).get('scan_key', 'F5').upper()
    trans_key = config.get('hotkeys', {}).get('translator_key', 'F7').upper()
    sec_trans_key = config.get('hotkeys', {}).get('secondary_translator_key', 'F8').upper()
    
    state_manager.is_running = False
    state_manager.set_restarting(False)
    last_known_state = None
    
    # --- KEYBOARD LISTENER ---
    def manual_toggle_listener():
        while getattr(threading.current_thread(), "do_run", True):
            try:
                if keyboard.is_pressed(hotkey):
                    start_time = time.time()
                    is_hold_action = False
                    
                    while keyboard.is_pressed(hotkey):
                        if time.time() - start_time > 0.3:
                            is_hold_action = True
                            state_manager.set_restarting(True)
                            while keyboard.is_pressed(hotkey):
                                time.sleep(0.05)
                            break
                        time.sleep(0.01)

                    if not is_hold_action:
                        current_state, _ = state_manager.get_state()
                        state_manager.is_running = not current_state
                    
                    time.sleep(0.2) 
                
                time.sleep(0.05) 
            except Exception:
                time.sleep(0.1)

    toggle_thread = threading.Thread(target=manual_toggle_listener, daemon=True)
    toggle_thread.do_run = True
    toggle_thread.start()
    
    print(f"{ui.Gradient.GREEN}[System] Хоткей {hotkey} активирован. (Клик=Пауза/Старт, Удерж.=Рестарт)")

    try:
        while True:
            try:
                is_running, is_restarting = state_manager.get_state()
                if is_running != last_known_state:
                    ui.clear_console()
                    ui.print_header()
                    if hasattr(ui, 'print_status_panel'):
                        ui.print_status_panel(is_running, mode, selected_profile, hotkey, scan_key)
                        print(f"{ui.Gradient.CYAN}Переводчик (Groq): {trans_key} - Основной, {sec_trans_key} - Вторая зона")
                        print(f"{ui.Gradient.CYAN}(Клик - перевод, Удержание {trans_key} - сброс контекста)")
                    else:
                        print(f"Статус: {is_running}, Режим: {mode}")
                    last_known_state = is_running

                if is_running or is_restarting:
                    if mode == "CLASSIC": main_cycle(selected_profile)
                    elif mode == "OCR": run_ocr_cycle()
                    elif mode == "MIXED": run_mixed_cycle(selected_profile)
                    
                    state_manager.is_running = False
                    state_manager.set_restarting(False)
                    last_known_state = None
                time.sleep(0.1)
            except Exception as e:
                print(f"{ui.Gradient.RED}Ошибка в Bot Loop: {e}")
                break
    finally:
        toggle_thread.do_run = False
        state_manager.is_running = False

def main():
    global overlay_thread
    try:
        config = load_config()
        
        msg_queue = queue.Queue()
        
        # --- START LOG PARSER ---
        if log_parser:
            log_parser.start_parser()
        
        if config.get("overlay_settings", {}).get("enabled", True):
            if OverlayController:
                overlay_thread = OverlayController(load_config, msg_queue)
                overlay_thread.start()
                print(f"{ui.Gradient.GREEN}[System] Визуальный оверлей запущен.")
        
        if worker_instance:
            try: 
                token = config.get('other_settings', {}).get('lzt_api_token', '')
                proxies = config.get('proxies', [])
                # Queue passed here is used for overlay updates in WebWorker and NicknameResolver
                worker_instance.set_api_token(token, proxies, msg_queue)
                worker_instance.start()
            except Exception as e: 
                print(f"{ui.Gradient.RED}[Main] Ошибка старта воркера: {e}")

        if translator_instance:
            translator_instance.configure(load_config)

        scan_hotkey = config.get('hotkeys', {}).get('scan_key', 'f5')
        trans_hotkey = config.get('hotkeys', {}).get('translator_key', 'f7')
        sec_trans_hotkey = config.get('hotkeys', {}).get('secondary_translator_key', 'f8')
        
        # --- BACKGROUND LISTENERS ---
        def background_scan_listener(key_name, m_queue):
            while True:
                try:
                    if keyboard.is_pressed(key_name):
                        start_time = time.time()
                        triggered_clear = False
                        while keyboard.is_pressed(key_name):
                            if time.time() - start_time > 0.3:
                                # HOLD > 0.3s: CLEAR QUEUE
                                if worker_instance: 
                                    worker_instance.clear_queue()
                                    if m_queue:
                                        m_queue.put({
                                            "type": "system",
                                            "text": "♻ MODULE RELOADED / QUEUE CLEARED"
                                        })
                                triggered_clear = True
                                while keyboard.is_pressed(key_name): time.sleep(0.05)
                                break
                            time.sleep(0.01)
                        # CLICK: SCAN
                        if not triggered_clear:
                            if perform_quick_scan: perform_quick_scan(load_config())
                            else: print(f"{ui.Gradient.RED}Скан недоступен (Модуль не загружен).")
                        time.sleep(0.2) 
                    time.sleep(0.05)
                except Exception: time.sleep(1)

        def background_translator_listener(key_f7, key_f8, m_queue):
            while True:
                try:
                    if keyboard.is_pressed(key_f7):
                        start_time = time.time()
                        is_hold_action = False
                        while keyboard.is_pressed(key_f7):
                            if time.time() - start_time > 0.3:
                                is_hold_action = True
                                if worker_instance: worker_instance.reset_translation_context()
                                while keyboard.is_pressed(key_f7): time.sleep(0.05)
                                break
                            time.sleep(0.01)
                        if not is_hold_action:
                            if worker_instance: worker_instance.add_translation_task(None)
                        time.sleep(0.2)

                    if keyboard.is_pressed(key_f8):
                        while keyboard.is_pressed(key_f8): time.sleep(0.05)
                        if worker_instance: worker_instance.add_translation_task("secondary")
                        time.sleep(0.2)
                    time.sleep(0.05)
                except Exception: time.sleep(1)

        if not any(t.name == "ScanListener" for t in threading.enumerate()):
            threading.Thread(target=background_scan_listener, args=(scan_hotkey, msg_queue), daemon=True, name="ScanListener").start()
        
        if not any(t.name == "TransListener" for t in threading.enumerate()) and translator_instance:
             threading.Thread(target=background_translator_listener, args=(trans_hotkey, sec_trans_hotkey, msg_queue), daemon=True, name="TransListener").start()

        selected_profile = config.get('other_settings', {}).get('last_selected_profile')
        if selected_profile and not os.path.exists(selected_profile): selected_profile = None

        while True: 
            ui.clear_console()
            ui.print_header()
            config = load_config()
            prof_name = os.path.basename(selected_profile) if selected_profile else 'Не выбран'
            
            print(f"{ui.Gradient.WHITE}1. Настройки (Общие)")
            print(f"{ui.Gradient.WHITE}2. Выбор профиля (Тек: {ui.Gradient.MEDIUM_CYAN}{prof_name}{ui.Gradient.WHITE})")
            print(f"{ui.Gradient.WHITE}3. Настройки OCR {ui.Gradient.YELLOW}(New)")
            print(f"{ui.Gradient.WHITE}5. Монитор сети / Дебаг")
            print(f"{ui.Gradient.GREEN}6. Запустить бота (Классика)")
            print(f"{ui.Gradient.CYAN}7. Запустить OCR режим (Beta)")
            print(f"{ui.Gradient.MIXED_COLOR}8. Запустить Смешанный режим")
            print(f"{ui.Gradient.YELLOW}11. Ручное добавление целей (ID/Links)") 
            print(f"{ui.Gradient.RED}0. Выход")
            
            choice = input(ui.Gradient.WHITE + "\nВаш выбор: ")

            if choice == '1': edit_settings() 
            elif choice == '2':
                p = select_profile()
                if p:
                    selected_profile = p
                    config['other_settings']['last_selected_profile'] = p
                    save_config(config)
            elif choice == '3': edit_settings(filter_category='ocr_settings')
            elif choice == '5':
                 network_monitor_loop()
            elif choice == '6':
                if not selected_profile: print(f"{ui.Gradient.RED}Сначала выберите профиль!"); time.sleep(1.5)
                else: run_bot_loop(selected_profile, mode="CLASSIC")
            elif choice == '7':
                run_bot_loop(mode="OCR")
            elif choice == '8':
                if not selected_profile: print(f"{ui.Gradient.RED}Для смешанного режима нужен профиль!"); time.sleep(1.5)
                else: run_bot_loop(selected_profile, mode="MIXED")
            elif choice == '11':
                if manual_input:
                    manual_input.run_manual_mode()
                else:
                    print(f"{ui.Gradient.RED}Модуль manual_input не найден!")
                    time.sleep(1.5)
            elif choice == '0': 
                cleanup_resources()
                sys.exit(0)
    except KeyboardInterrupt:
        cleanup_resources()
        sys.exit(0)
    except Exception as e:
        print(f"\n{ui.Gradient.RED}КРИТИЧЕСКАЯ ОШИБКА МЕНЮ:\n{e}\n{traceback.format_exc()}")
        cleanup_resources()
        input("Enter для выхода...")

if __name__ == "__main__":
    main()