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
except Exception:
    ocr_scanner = None

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

# --- FACEIT HUNTER IMPORT ---
try:
    from faceit_hunter import faceit_hunter_instance
    FACEIT_HUNTER_AVAILABLE = True
except ImportError:
    faceit_hunter_instance = None
    FACEIT_HUNTER_AVAILABLE = False
    print(f"{ui.Gradient.YELLOW}[Warning] faceit_hunter.py не найден.")

overlay_thread = None

def cleanup_resources():
    global overlay_thread
    if worker_instance:
        try:
            worker_instance.stop()
        except:
            pass
    if overlay_thread:
        try:
            overlay_thread.stop()
        except:
            pass
    # Stop log parser
    if log_parser:
        try:
            log_parser.stop_parser()
        except:
            pass
    try:
        keyboard.unhook_all()
    except:
        pass

def win_handler(ctrl_type):
    cleanup_resources()
    return True

if os.name == 'nt':
    PHANDLER_ROUTINE = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_uint)
    handler = PHANDLER_ROUTINE(win_handler)
    ctypes.windll.kernel32.SetConsoleCtrlHandler(handler, True)

def select_profile():
    profiles_dir = 'profiles'
    if not os.path.exists(profiles_dir):
        os.makedirs(profiles_dir)
    if not os.listdir(profiles_dir):
        print(f"{ui.Gradient.RED}Папка 'profiles' пуста.")
        time.sleep(2)
        return None
    profiles = [f for f in os.listdir(profiles_dir) if f.endswith('.json')]
    while True:
        ui.clear_console()
        print("\n" + ui.Gradient.YELLOW + "--- Выбор профиля ---")
        for i, profile in enumerate(profiles, 1):
            print(f"{ui.Gradient.MEDIUM_CYAN}{i}. {profile}")
        print(f"{ui.Gradient.RED}0. Назад")
        try:
            choice = input(ui.Gradient.WHITE + "Выберите профиль: ")
            if choice == '0':
                return None
            choice_num = int(choice)
            if 1 <= choice_num <= len(profiles):
                return os.path.join(profiles_dir, profiles[choice_num - 1])
        except ValueError:
            pass

def network_monitor_loop():
    """Interactive Network Monitor"""
    if not worker_instance:
        print(f"{ui.Gradient.RED}Воркер не инициализирован. Запустите бота хотя бы раз или проверьте конфиг.")
        time.sleep(2)
        return

    def mask_proxy(proxy_str):
        if not proxy_str:
            return "Direct (Local)"
        if "@" in proxy_str:
            return proxy_str.split("@")[-1]
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
                if p_score < 0:
                    score_col = ui.Gradient.RED
                elif p_score > 10:
                    score_col = ui.Gradient.GREEN

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
        print(f"Nick Resolver       | {nick_status}{ui.Gradient.WHITE} | {nick_info}")

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
        print(f"Groq Translator     | {trans_status}{ui.Gradient.WHITE} | {trans_info}")

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
        print(f"Log Parser          | {parser_status}{ui.Gradient.WHITE} | {parser_info}")

        print("-" * 60)

        print(f"\n{ui.Gradient.WHITE}Queues: Main={worker_instance.queue.qsize()} | Retry/API={worker_instance.retry_queue.qsize()}")

        print(f"\n{ui.Gradient.CYAN}[1/Enter] Обновить [2] DEEP DEBUG (Анализ проблем) [0] Назад в меню")
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
                    if mode == "CLASSIC":
                        main_cycle(selected_profile)
                    elif mode == "OCR":
                        run_ocr_cycle()
                    elif mode == "MIXED":
                        run_mixed_cycle(selected_profile)

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

# ═══════════════════════════════════════════════════════════════════════
# FACEIT HUNTER MENU FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════

def faceit_hunter_menu():
    """Меню Faceit Hunter"""
    if not FACEIT_HUNTER_AVAILABLE:
        print(f"{ui.Gradient.RED}Faceit Hunter не установлен!")
        time.sleep(2)
        return

    while True:
        ui.clear_console()
        ui.print_header()

        # Получаем статус
        is_running = faceit_hunter_instance.is_running
        mode = faceit_hunter_instance.mode or "None"

        print(f"{ui.Gradient.CYAN}╔══════════════════════════════════════════════════════════════╗")
        print(f"{ui.Gradient.CYAN}║            🎮 FACEIT HUNTER - Меню                          ║")
        print(f"{ui.Gradient.CYAN}╚══════════════════════════════════════════════════════════════╝")
        print()

        # Статус
        if is_running:
            status_text = f"{ui.Gradient.GREEN}▶️ ACTIVE - {mode.upper()}"
        else:
            status_text = f"{ui.Gradient.RED}⏸️ INACTIVE"

        print(f"Status: {status_text}{ui.Gradient.WHITE}")
        print()

        # Меню
        print(f"{ui.Gradient.YELLOW}═══ РЕЖИМЫ ═══")
        print(f"{ui.Gradient.WHITE}1. 🎪 Party Hunter - поиск игроков в party")
        print(f"{ui.Gradient.WHITE}2. 🛡️ Guard Mode - защита лобби от нубов")
        print()

        print(f"{ui.Gradient.YELLOW}═══ УПРАВЛЕНИЕ ═══")
        if is_running:
            print(f"{ui.Gradient.RED}3. ⏹️ Остановить")
        else:
            print(f"{ui.Gradient.GREEN}3. (Выберите режим выше)")

        print(f"{ui.Gradient.WHITE}4. ⚙️ Настройки")
        print(f"{ui.Gradient.WHITE}5. 📊 Статистика")
        print()

        print(f"{ui.Gradient.YELLOW}═══ СТАТУС ═══")
        stats_party = faceit_hunter_instance.stats['party_hunter']
        stats_guard = faceit_hunter_instance.stats['guard_mode']
        print(f"{ui.Gradient.WHITE}Party Hunter: Scanned={stats_party['scanned']}, Added={stats_party['added']}, Skipped={stats_party['skipped']}")
        print(f"{ui.Gradient.WHITE}Guard Mode: Checked={stats_guard['checked']}, Kicked={stats_guard['kicked']}, Passed={stats_guard['passed']}")
        print()

        print(f"{ui.Gradient.RED}0. Назад")
        print()

        choice = input(ui.Gradient.WHITE + "Ваш выбор: ")

        if choice == '1':
            if not is_running:
                print(f"{ui.Gradient.CYAN}Запуск Party Hunter...")
                print(f"{ui.Gradient.YELLOW}⚠️ Убедитесь что Firefox запущен (start_firefox.bat) и вы залогинены на Faceit!")
                time.sleep(2)
                if faceit_hunter_instance.start('party_hunter'):
                    print(f"{ui.Gradient.GREEN}✅ Party Hunter запущен!")
                else:
                    print(f"{ui.Gradient.RED}❌ Ошибка запуска. Проверьте start_firefox.bat")
                time.sleep(2)
            else:
                print(f"{ui.Gradient.YELLOW}Уже запущен!")
                time.sleep(1)

        elif choice == '2':
            if not is_running:
                print(f"{ui.Gradient.CYAN}Запуск Guard Mode...")
                print(f"{ui.Gradient.YELLOW}⚠️ Сначала создайте лобби на Faceit вручную!")
                time.sleep(2)
                if faceit_hunter_instance.start('guard_mode'):
                    print(f"{ui.Gradient.GREEN}✅ Guard Mode запущен!")
                    print(f"{ui.Gradient.YELLOW}⚠️ Создайте лобби на Faceit вручную!")
                else:
                    print(f"{ui.Gradient.RED}❌ Ошибка запуска. Проверьте start_firefox.bat")
                time.sleep(3)
            else:
                print(f"{ui.Gradient.YELLOW}Уже запущен!")
                time.sleep(1)

        elif choice == '3':
            if is_running:
                faceit_hunter_instance.stop()
                print(f"{ui.Gradient.GREEN}✅ Остановлен")
                time.sleep(1)

        elif choice == '4':
            faceit_hunter_settings_menu()

        elif choice == '5':
            faceit_hunter_stats_menu()

        elif choice == '0':
            break

def faceit_hunter_settings_menu():
    """Меню настроек Faceit Hunter"""
    while True:
        ui.clear_console()
        print(f"{ui.Gradient.CYAN}╔══════════════════════════════════════════════════════════════╗")
        print(f"{ui.Gradient.CYAN}║            ⚙️ FACEIT HUNTER - Настройки                      ║")
        print(f"{ui.Gradient.CYAN}╚══════════════════════════════════════════════════════════════╝")
        print()

        config = faceit_hunter_instance.config

        print(f"{ui.Gradient.YELLOW}═══ PARTY HUNTER ═══")
        print(f"{ui.Gradient.WHITE}1. Минимальная стоимость: {config['party_hunter']['min_value_rub']}₽")
        print(f"{ui.Gradient.WHITE}2. Интервал сканирования: {config['party_hunter']['scan_interval']}с")
        print(f"{ui.Gradient.WHITE}3. Макс. друзей за сессию: {config['party_hunter']['max_friends_per_session']}")
        print()

        print(f"{ui.Gradient.YELLOW}═══ GUARD MODE ═══")
        print(f"{ui.Gradient.WHITE}4. Минимальная стоимость: {config['guard_mode']['min_value_rub']}₽")
        print(f"{ui.Gradient.WHITE}5. Auto-bump: {config['guard_mode']['auto_bump']}")
        print(f"{ui.Gradient.WHITE}6. Интервал бампа: {config['guard_mode']['bump_interval']}с")
        print()

        print(f"{ui.Gradient.RED}0. Назад")
        print()

        choice = input(ui.Gradient.WHITE + "Выберите настройку: ")

        if choice == '1':
            try:
                val = int(input("Новое значение (₽): "))
                config['party_hunter']['min_value_rub'] = val
                faceit_hunter_instance.save_config()
                print(f"{ui.Gradient.GREEN}✅ Сохранено!")
                time.sleep(1)
            except:
                print(f"{ui.Gradient.RED}❌ Неверное значение")
                time.sleep(1)

        elif choice == '2':
            try:
                val = int(input("Новое значение (секунды): "))
                config['party_hunter']['scan_interval'] = val
                faceit_hunter_instance.save_config()
                print(f"{ui.Gradient.GREEN}✅ Сохранено!")
                time.sleep(1)
            except:
                print(f"{ui.Gradient.RED}❌ Неверное значение")
                time.sleep(1)

        elif choice == '3':
            try:
                val = int(input("Новое значение: "))
                config['party_hunter']['max_friends_per_session'] = val
                faceit_hunter_instance.save_config()
                print(f"{ui.Gradient.GREEN}✅ Сохранено!")
                time.sleep(1)
            except:
                print(f"{ui.Gradient.RED}❌ Неверное значение")
                time.sleep(1)

        elif choice == '4':
            try:
                val = int(input("Новое значение (₽): "))
                config['guard_mode']['min_value_rub'] = val
                faceit_hunter_instance.save_config()
                print(f"{ui.Gradient.GREEN}✅ Сохранено!")
                time.sleep(1)
            except:
                print(f"{ui.Gradient.RED}❌ Неверное значение")
                time.sleep(1)

        elif choice == '5':
            config['guard_mode']['auto_bump'] = not config['guard_mode']['auto_bump']
            faceit_hunter_instance.save_config()
            print(f"{ui.Gradient.GREEN}✅ Сохранено!")
            time.sleep(1)

        elif choice == '6':
            try:
                val = int(input("Новое значение (секунды): "))
                config['guard_mode']['bump_interval'] = val
                faceit_hunter_instance.save_config()
                print(f"{ui.Gradient.GREEN}✅ Сохранено!")
                time.sleep(1)
            except:
                print(f"{ui.Gradient.RED}❌ Неверное значение")
                time.sleep(1)

        elif choice == '0':
            break

def faceit_hunter_stats_menu():
    """Детальная статистика"""
    ui.clear_console()
    print(f"{ui.Gradient.CYAN}╔══════════════════════════════════════════════════════════════╗")
    print(f"{ui.Gradient.CYAN}║            📊 FACEIT HUNTER - Статистика                     ║")
    print(f"{ui.Gradient.CYAN}╚══════════════════════════════════════════════════════════════╝")
    print()

    stats_party = faceit_hunter_instance.stats['party_hunter']
    stats_guard = faceit_hunter_instance.stats['guard_mode']

    print(f"{ui.Gradient.YELLOW}═══ PARTY HUNTER ═══")
    print(f"{ui.Gradient.WHITE}Просканировано игроков: {stats_party['scanned']}")
    print(f"{ui.Gradient.GREEN}Добавлено в друзья: {stats_party['added']}")
    print(f"{ui.Gradient.RED}Пропущено: {stats_party['skipped']}")
    print()

    print(f"{ui.Gradient.YELLOW}═══ GUARD MODE ═══")
    print(f"{ui.Gradient.WHITE}Проверено игроков: {stats_guard['checked']}")
    print(f"{ui.Gradient.RED}Кикнуто: {stats_guard['kicked']}")
    print(f"{ui.Gradient.GREEN}Допущено: {stats_guard['passed']}")
    print()

    print(f"{ui.Gradient.YELLOW}═══ ДОПОЛНИТЕЛЬНО ═══")
    print(f"{ui.Gradient.WHITE}Всего добавлено в друзья: {len(faceit_hunter_instance.added_players)}")
    print(f"{ui.Gradient.WHITE}Всего кикнуто: {len(faceit_hunter_instance.kicked_players)}")
    print()

    input(f"{ui.Gradient.WHITE}Нажмите Enter для возврата...")

# ═══════════════════════════════════════════════════════════════════════
# MAIN FUNCTION
# ═══════════════════════════════════════════════════════════════════════

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
                                while keyboard.is_pressed(key_name):
                                    time.sleep(0.05)
                                break
                            time.sleep(0.01)
                        # CLICK: SCAN
                        if not triggered_clear:
                            if perform_quick_scan:
                                perform_quick_scan(load_config())
                            else:
                                print(f"{ui.Gradient.RED}Скан недоступен (Модуль не загружен).")
                        time.sleep(0.2)
                    time.sleep(0.05)
                except Exception:
                    time.sleep(1)

        def background_translator_listener(key_f7, key_f8, m_queue):
            while True:
                try:
                    if keyboard.is_pressed(key_f7):
                        start_time = time.time()
                        is_hold_action = False
                        while keyboard.is_pressed(key_f7):
                            if time.time() - start_time > 0.3:
                                is_hold_action = True
                                if worker_instance:
                                    worker_instance.reset_translation_context()
                                while keyboard.is_pressed(key_f7):
                                    time.sleep(0.05)
                                break
                            time.sleep(0.01)
                        if not is_hold_action:
                            if worker_instance:
                                worker_instance.add_translation_task(None)
                        time.sleep(0.2)

                    if keyboard.is_pressed(key_f8):
                        while keyboard.is_pressed(key_f8):
                            time.sleep(0.05)
                        if worker_instance:
                            worker_instance.add_translation_task("secondary")
                        time.sleep(0.2)

                    time.sleep(0.05)
                except Exception:
                    time.sleep(1)

        if not any(t.name == "ScanListener" for t in threading.enumerate()):
            threading.Thread(target=background_scan_listener, args=(scan_hotkey, msg_queue), daemon=True, name="ScanListener").start()

        if not any(t.name == "TransListener" for t in threading.enumerate()) and translator_instance:
            threading.Thread(target=background_translator_listener, args=(trans_hotkey, sec_trans_hotkey, msg_queue), daemon=True, name="TransListener").start()

        selected_profile = config.get('other_settings', {}).get('last_selected_profile')
        if selected_profile and not os.path.exists(selected_profile):
            selected_profile = None

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
            print(f"{ui.Gradient.YELLOW}9. 🎮 Faceit Hunter")
            print(f"{ui.Gradient.YELLOW}11. Ручное добавление целей (ID/Links)")
            print(f"{ui.Gradient.RED}0. Выход")

            choice = input(ui.Gradient.WHITE + "\nВаш выбор: ")

            if choice == '1':
                edit_settings()
            elif choice == '2':
                p = select_profile()
                if p:
                    selected_profile = p
                    config['other_settings']['last_selected_profile'] = p
                    save_config(config)
            elif choice == '3':
                edit_settings(filter_category='ocr_settings')
            elif choice == '5':
                network_monitor_loop()
            elif choice == '6':
                if not selected_profile:
                    print(f"{ui.Gradient.RED}Сначала выберите профиль!")
                    time.sleep(1.5)
                else:
                    run_bot_loop(selected_profile, mode="CLASSIC")
            elif choice == '7':
                run_bot_loop(mode="OCR")
            elif choice == '8':
                if not selected_profile:
                    print(f"{ui.Gradient.RED}Для смешанного режима нужен профиль!")
                    time.sleep(1.5)
                else:
                    run_bot_loop(selected_profile, mode="MIXED")
            elif choice == '9':
                faceit_hunter_menu()
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
