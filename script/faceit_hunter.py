"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                    FACEIT HUNTER - Party Hunter & Guard Mode                 ║
║                 Интеграция с существующей системой проверки                  ║
║                          Firefox Edition                                     ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import time
import json
import logging
import threading
import re
import requests
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from colorama import Fore, Style

# Импорты из существующей системы
try:
    import web_worker
    import logger
    from config_utils import load_config
    SYSTEM_AVAILABLE = True
except ImportError:
    SYSTEM_AVAILABLE = False
    print("⚠️ Warning: web_worker.py not found!")

class FaceitHunter:
    def __init__(self):
        self.driver = None
        self.is_running = False
        self.mode = None  # 'party_hunter' или 'guard_mode'
        self.config = self.load_faceit_config()

        # Инициализация web_worker (используем СУЩЕСТВУЮЩУЮ систему!)
        self.web_worker_instance = None
        if SYSTEM_AVAILABLE:
            self.web_worker_instance = web_worker.WebWorker()
            self.log("✅ Web Worker загружен (используем вашу систему проверки)", "SUCCESS")

        self.checked_players = set()
        self.added_players = set()
        self.kicked_players = set()

        # Статистика
        self.stats = {
            'party_hunter': {'scanned': 0, 'added': 0, 'skipped': 0},
            'guard_mode': {'checked': 0, 'kicked': 0, 'passed': 0}
        }

    def load_faceit_config(self):
        """Загрузка конфигурации Faceit Hunter"""
        try:
            with open('faceit_config.json', 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            # Конфиг по умолчанию
            default_config = {
                "party_hunter": {
                    "enabled": True,
                    "min_value_rub": 300,
                    "scan_interval": 60,
                    "blacklist": [],
                    "max_friends_per_session": 20
                },
                "guard_mode": {
                    "enabled": True,
                    "min_value_rub": 150,
                    "whitelist": [],
                    "auto_bump": True,
                    "bump_interval": 300
                },
                "browser": {
                    "type": "firefox",
                    "debug_port": 9222,
                    "firefox_profile": ""
                }
            }
            with open('faceit_config.json', 'w', encoding='utf-8') as f:
                json.dump(default_config, f, indent=4)
            return default_config

    def save_config(self):
        """Сохранение конфигурации"""
        with open('faceit_config.json', 'w', encoding='utf-8') as f:
            json.dump(self.config, f, indent=4)

    def log(self, message, level="INFO"):
        """Логирование сообщений"""
        timestamp = datetime.now().strftime('%H:%M:%S')

        if level == "SUCCESS":
            colored_msg = f"{Fore.GREEN}[Faceit] {message}{Style.RESET_ALL}"
        elif level == "WARNING":
            colored_msg = f"{Fore.YELLOW}[Faceit] {message}{Style.RESET_ALL}"
        elif level == "ERROR":
            colored_msg = f"{Fore.RED}[Faceit] {message}{Style.RESET_ALL}"
        else:
            colored_msg = f"{Fore.CYAN}[Faceit] {message}{Style.RESET_ALL}"

        print(f"{timestamp} - {colored_msg}")

        if SYSTEM_AVAILABLE:
            try:
                logger.log_worker(message, level=level)
            except:
                pass

    def connect_to_browser(self):
        """Подключение к открытому Firefox"""
        self.log("Connecting to Firefox browser...")

        try:
            browser_type = self.config['browser'].get('type', 'firefox')

            if browser_type == 'firefox':
                return self._connect_firefox()
            else:
                return self._connect_chrome()

        except Exception as e:
            self.log(f"❌ Failed to connect to browser: {e}", "ERROR")
            self.log("", "INFO")
            self.log("═" * 70, "INFO")
            self.log("ИНСТРУКЦИЯ:", "WARNING")
            self.log("1. Закройте все окна Firefox", "INFO")
            self.log("2. Запустите start_firefox.bat", "INFO")
            self.log("3. Зайдите на Faceit.com и залогиньтесь", "INFO")
            self.log("4. Запустите Faceit Hunter снова", "INFO")
            self.log("═" * 70, "INFO")
            return False

    def _connect_firefox(self):
        """Подключение к Firefox через Marionette"""
        try:
            # Для Firefox используем обычное подключение с профилем
            options = webdriver.FirefoxOptions()

            # Используем существующий профиль если указан
            firefox_profile = self.config['browser'].get('firefox_profile', '')
            if firefox_profile:
                options.add_argument('-profile')
                options.add_argument(firefox_profile)

            # Отключаем headless режим (видим браузер)
            # options.add_argument('--headless')  # Закомментировано - хотим видеть

            self.driver = webdriver.Firefox(options=options)

            self.log("✅ Connected to Firefox successfully!", "SUCCESS")
            return True

        except Exception as e:
            self.log(f"❌ Firefox connection error: {e}", "ERROR")
            return False

    def _connect_chrome(self):
        """Подключение к Chrome через debug port"""
        try:
            debug_port = self.config['browser']['debug_port']

            options = webdriver.ChromeOptions()
            options.add_experimental_option("debuggerAddress", f"127.0.0.1:{debug_port}")

            self.driver = webdriver.Chrome(options=options)

            self.log("✅ Connected to Chrome successfully!", "SUCCESS")
            return True

        except Exception as e:
            self.log(f"❌ Chrome connection error: {e}", "ERROR")
            return False

    def get_steam_id_from_faceit(self, nickname):
        """Получение Steam ID через Faceit API"""
        try:
            url = f"https://www.faceit.com/api/users/v1/nicknames/{nickname}"
            response = requests.get(url, timeout=10)

            if response.status_code != 200:
                return None

            data = response.json()
            payload = data.get('payload', {})

            # Ищем Steam ID в разных местах
            steam_id = (
                payload.get('platforms', {}).get('steam', {}).get('id64') or
                payload.get('games', {}).get('cs2', {}).get('game_id') or
                payload.get('games', {}).get('csgo', {}).get('game_id')
            )

            return steam_id

        except Exception as e:
            self.log(f"Error getting Steam ID for {nickname}: {e}", "ERROR")
            return None

    def check_inventory_via_web_worker(self, steam_id, nickname):
        """Проверка инвентаря через ВАШУ систему web_worker"""
        if not self.web_worker_instance:
            self.log("Web Worker not available!", "ERROR")
            return 0

        try:
            # Добавляем Steam ID в очередь проверки
            self.log(f"  Добавляем {nickname} в очередь проверки...")

            # Используем метод add_steam_id из вашего web_worker
            self.web_worker_instance.add_steam_id(steam_id, ignore_cache=False)

            # Ждем результата проверки
            max_wait = 30  # Максимум 30 секунд ждем
            start_time = time.time()

            while (time.time() - start_time) < max_wait:
                time.sleep(1)

                # Проверяем завершена ли проверка
                if not self.web_worker_instance.is_running():
                    break

            self.log(f"  ⚠️ Проверка через web_worker (результат нужно получить из вашей системы)", "WARNING")
            return 0

        except Exception as e:
            self.log(f"Error checking inventory: {e}", "ERROR")
            return 0

    def check_player(self, nickname):
        """Проверка игрока: Steam ID + Инвентарь"""
        if nickname in self.checked_players:
            return None

        self.checked_players.add(nickname)

        self.log(f"Checking player: {nickname}")

        # Получаем Steam ID
        steam_id = self.get_steam_id_from_faceit(nickname)
        if not steam_id:
            self.log(f"  ❌ No Steam ID found for {nickname}", "WARNING")
            return None

        self.log(f"  Steam ID: {steam_id}")

        # ИСПОЛЬЗУЕМ ВАШУ СИСТЕМУ для проверки инвентаря
        inv_value = self.check_inventory_via_web_worker(steam_id, nickname)

        self.log(f"  Inventory: {inv_value}₽")

        return {
            'nickname': nickname,
            'steam_id': steam_id,
            'inventory_value': inv_value
        }

    # ═══════════════════════════════════════════════════════════════════════
    # PARTY HUNTER MODE
    # ═══════════════════════════════════════════════════════════════════════

    def run_party_hunter(self):
        """Режим Party Hunter"""
        self.log("═" * 70, "INFO")
        self.log("🎪 PARTY HUNTER MODE STARTED", "SUCCESS")
        self.log("═" * 70, "INFO")

        config = self.config['party_hunter']
        min_value = config['min_value_rub']
        scan_interval = config['scan_interval']
        blacklist = set(config.get('blacklist', []))
        max_friends = config.get('max_friends_per_session', 20)

        self.log(f"Settings: Min Value = {min_value}₽, Interval = {scan_interval}s")

        # Открываем вкладку с parties
        try:
            self.driver.execute_script("window.open('https://www.faceit.com/en/csgo/parties', '_blank');")
            time.sleep(2)

            # Переключаемся на новую вкладку
            self.driver.switch_to.window(self.driver.window_handles[-1])
            time.sleep(3)

        except Exception as e:
            self.log(f"Error opening parties page: {e}", "ERROR")
            return

        while self.is_running:
            try:
                self.log("─" * 70, "INFO")
                self.log("Scanning parties...")

                # Парсим parties
                parties = self.parse_parties_page()

                if not parties:
                    self.log("No parties found", "WARNING")
                    time.sleep(scan_interval)
                    continue

                self.log(f"Found {len(parties)} active parties")

                # Собираем все ники для массовой проверки
                all_nicknames = []
                for party in parties:
                    players = party.get('players', [])
                    for player_nick in players:
                        if player_nick not in blacklist and player_nick not in self.added_players:
                            all_nicknames.append((player_nick, party.get('name', 'Unknown')))

                self.log(f"Total players to check: {len(all_nicknames)}")

                # Получаем Steam ID для всех игроков
                steam_ids_to_check = []
                nickname_to_steam = {}

                for nickname, party_name in all_nicknames:
                    if not self.is_running:
                        break

                    steam_id = self.get_steam_id_from_faceit(nickname)
                    if steam_id:
                        steam_ids_to_check.append(steam_id)
                        nickname_to_steam[steam_id] = (nickname, party_name)
                        self.log(f"  {nickname} → {steam_id}")
                    else:
                        self.stats['party_hunter']['skipped'] += 1

                if not steam_ids_to_check:
                    self.log("No Steam IDs found", "WARNING")
                    time.sleep(scan_interval)
                    continue

                # МАССОВАЯ ПРОВЕРКА через ваш web_worker
                self.log(f"Запуск массовой проверки {len(steam_ids_to_check)} игроков через WebWorker...")

                if self.web_worker_instance:
                    # Добавляем все Steam ID в очередь
                    for steam_id in steam_ids_to_check:
                        self.web_worker_instance.add_steam_id(steam_id, ignore_cache=False)

                    # Запускаем проверку
                    if not self.web_worker_instance.is_running():
                        worker_thread = threading.Thread(target=self.web_worker_instance.run, daemon=True)
                        worker_thread.start()

                    # Ждем завершения проверки
                    self.log("Ожидание результатов проверки...")
                    while self.web_worker_instance.is_running() and self.is_running:
                        time.sleep(2)

                    self.log("✅ Проверка завершена!")

                    # TODO: Получить результаты из вашей системы
                    self.log("⚠️ TODO: Получить результаты из вашей системы и добавить игроков", "WARNING")

                self.print_stats('party_hunter')

                # Пауза перед следующим сканом
                if self.is_running:
                    self.log(f"Waiting {scan_interval}s before next scan...")
                    time.sleep(scan_interval)

            except Exception as e:
                self.log(f"Error in party hunter loop: {e}", "ERROR")
                time.sleep(10)

    def parse_parties_page(self):
        """Парсинг страницы с parties"""
        try:
            # Скроллим страницу
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1)

            parties = []

            # Ищем элементы с party
            party_elements = self.driver.find_elements(By.CSS_SELECTOR, "[class*='party'], [class*='Party']")

            for party_elem in party_elements[:10]:
                try:
                    # Извлекаем название party
                    try:
                        party_name = party_elem.find_element(By.CSS_SELECTOR, "[class*='name'], [class*='title']").text
                    except:
                        party_name = "Unknown Party"

                    # Извлекаем игроков
                    player_elements = party_elem.find_elements(By.CSS_SELECTOR, "[class*='nickname'], a[href*='/players/']")
                    players = []

                    for player_elem in player_elements:
                        nick = player_elem.text.strip()
                        if nick and len(nick) > 2:
                            players.append(nick)

                    if players:
                        parties.append({
                            'name': party_name,
                            'players': players
                        })

                except Exception as e:
                    continue

            return parties

        except Exception as e:
            self.log(f"Error parsing parties: {e}", "ERROR")
            return []

    def add_friend(self, nickname):
        """Добавление игрока в друзья"""
        try:
            # Открываем профиль игрока в новой вкладке
            profile_url = f"https://www.faceit.com/en/players/{nickname}"
            self.driver.execute_script(f"window.open('{profile_url}', '_blank');")
            time.sleep(1)

            # Переключаемся на вкладку с профилем
            original_window = self.driver.current_window_handle
            self.driver.switch_to.window(self.driver.window_handles[-1])
            time.sleep(2)

            # Ищем кнопку "Add Friend"
            try:
                add_button = WebDriverWait(self.driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Add') or contains(text(), 'Friend')]"))
                )
                add_button.click()
                time.sleep(1)
                success = True
            except:
                success = False

            # Закрываем вкладку и возвращаемся
            self.driver.close()
            self.driver.switch_to.window(original_window)

            return success

        except Exception as e:
            self.log(f"Error adding friend: {e}", "ERROR")
            try:
                self.driver.switch_to.window(self.driver.window_handles[0])
            except:
                pass
            return False

    # ═══════════════════════════════════════════════════════════════════════
    # GUARD MODE
    # ═══════════════════════════════════════════════════════════════════════

    def run_guard_mode(self):
        """Режим Guard Mode"""
        self.log("═" * 70, "INFO")
        self.log("🛡️ GUARD MODE STARTED", "SUCCESS")
        self.log("═" * 70, "INFO")

        config = self.config['guard_mode']
        min_value = config['min_value_rub']
        whitelist = set(config.get('whitelist', []))

        self.log(f"Settings: Min Value = {min_value}₽")
        self.log("Waiting for lobby... Please create/join a lobby manually")

        last_bump_time = time.time()
        bump_interval = config.get('bump_interval', 300)

        # Ждем пока пользователь создаст/зайдет в лобби
        lobby_url_pattern = re.compile(r'faceit\.com.*/room/')

        while self.is_running:
            try:
                current_url = self.driver.current_url

                if not lobby_url_pattern.search(current_url):
                    time.sleep(2)
                    continue

                self.log(f"✅ Lobby detected: {current_url}", "SUCCESS")
                break

            except:
                time.sleep(2)

        # Основной цикл Guard Mode
        previous_players = set()

        while self.is_running:
            try:
                # Получаем список игроков в лобби
                current_players = self.get_lobby_players()

                # Проверяем новых игроков
                new_players = current_players - previous_players

                if new_players:
                    self.log(f"New players detected: {len(new_players)}")

                    # Собираем Steam ID для массовой проверки
                    steam_ids_to_check = []
                    nickname_to_steam = {}

                    for player_nick in new_players:
                        if not self.is_running:
                            break

                        self.log(f"New player joined: {player_nick}")

                        # Whitelist check
                        if player_nick in whitelist:
                            self.log(f"  ✅ {player_nick} - whitelisted", "SUCCESS")
                            self.stats['guard_mode']['passed'] += 1
                            continue

                        # Получаем Steam ID
                        steam_id = self.get_steam_id_from_faceit(player_nick)
                        if steam_id:
                            steam_ids_to_check.append(steam_id)
                            nickname_to_steam[steam_id] = player_nick
                            self.log(f"  {player_nick} → {steam_id}")
                        else:
                            self.log(f"  ⚠️ {player_nick} - no Steam ID", "WARNING")

                    # Массовая проверка через web_worker
                    if steam_ids_to_check and self.web_worker_instance:
                        self.log(f"Checking {len(steam_ids_to_check)} players via WebWorker...")

                        for steam_id in steam_ids_to_check:
                            self.web_worker_instance.add_steam_id(steam_id, ignore_cache=False)

                        # Запускаем проверку
                        if not self.web_worker_instance.is_running():
                            worker_thread = threading.Thread(target=self.web_worker_instance.run, daemon=True)
                            worker_thread.start()

                        # Ждем результатов
                        while self.web_worker_instance.is_running() and self.is_running:
                            time.sleep(1)

                        self.log("✅ Проверка завершена!")

                        # TODO: Получить результаты и кикнуть игроков с низким инвентарем
                        self.log("⚠️ TODO: Получить результаты и выполнить кики", "WARNING")

                previous_players = current_players

                # Auto-bump
                if config.get('auto_bump') and (time.time() - last_bump_time) > bump_interval:
                    self.log("🔄 Auto-bumping lobby...")
                    self.bump_lobby()
                    last_bump_time = time.time()

                self.print_stats('guard_mode')

                time.sleep(3)

            except Exception as e:
                self.log(f"Error in guard mode loop: {e}", "ERROR")
                time.sleep(5)

    def get_lobby_players(self):
        """Получение списка игроков в лобби"""
        try:
            player_elements = self.driver.find_elements(By.CSS_SELECTOR, "[class*='nickname'], [class*='player-name']")

            players = set()
            for elem in player_elements:
                nick = elem.text.strip()
                if nick and len(nick) > 2:
                    players.add(nick)

            return players

        except Exception as e:
            self.log(f"Error getting lobby players: {e}", "ERROR")
            return set()

    def kick_player(self, nickname):
        """Кик игрока из лобби"""
        try:
            kick_buttons = self.driver.find_elements(By.XPATH, 
                f"//div[contains(text(), '{nickname}')]/ancestor::div[contains(@class, 'player')]//button[contains(@class, 'kick') or contains(text(), 'Kick')]"
            )

            if kick_buttons:
                kick_buttons[0].click()
                time.sleep(1)

                try:
                    confirm_button = WebDriverWait(self.driver, 3).until(
                        EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Confirm') or contains(text(), 'Yes')]"))
                    )
                    confirm_button.click()
                except:
                    pass

                return True

            return False

        except Exception as e:
            self.log(f"Error kicking player: {e}", "ERROR")
            return False

    def bump_lobby(self):
        """Бамп лобби"""
        try:
            bump_button = self.driver.find_element(By.XPATH, "//button[contains(text(), 'Bump') or contains(@class, 'bump')]")
            bump_button.click()
            time.sleep(1)
            return True
        except:
            return False

    # ═══════════════════════════════════════════════════════════════════════
    # УТИЛИТЫ
    # ═══════════════════════════════════════════════════════════════════════

    def print_stats(self, mode):
        """Вывод статистики"""
        stats = self.stats[mode]

        if mode == 'party_hunter':
            self.log(f"📊 Stats: Scanned={stats['scanned']}, Added={stats['added']}, Skipped={stats['skipped']}")
        else:
            self.log(f"📊 Stats: Checked={stats['checked']}, Kicked={stats['kicked']}, Passed={stats['passed']}")

    def start(self, mode='party_hunter'):
        """Запуск модуля"""
        if self.is_running:
            self.log("Already running!", "WARNING")
            return False

        if not self.connect_to_browser():
            return False

        self.is_running = True
        self.mode = mode

        if mode == 'party_hunter':
            thread = threading.Thread(target=self.run_party_hunter, daemon=True)
        else:
            thread = threading.Thread(target=self.run_guard_mode, daemon=True)

        thread.start()
        return True

    def stop(self):
        """Остановка модуля"""
        self.log("Stopping Faceit Hunter...")
        self.is_running = False

        if self.driver:
            try:
                self.driver.quit()
            except:
                pass

        self.log("✅ Stopped", "SUCCESS")

# Глобальный инстанс
faceit_hunter_instance = FaceitHunter()

if __name__ == "__main__":
    hunter = FaceitHunter()
    hunter.start('party_hunter')

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        hunter.stop()
