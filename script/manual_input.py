import os
import re
import time
import requests
import ui
from web_worker import worker_instance

# Константа для конвертации ID32 -> ID64
STEAM_BASELINE = 76561197960265728

def get_steamid64_from_url(url):
    """
    Пытается извлечь ID64 из ссылки.
    Если это /profiles/ - достает регуляркой.
    Если это /id/ (Vanity URL) - делает запрос к API Steam (XML) без прокси.
    """
    # 1. Ссылка вида /profiles/765...
    match_profile = re.search(r"profiles/(\d{17})", url)
    if match_profile:
        return match_profile.group(1)

    # 2. Ссылка вида /id/custom_name
    match_id = re.search(r"id/([^/]+)", url)
    if match_id:
        vanity_name = match_id.group(1)
        xml_url = f"https://steamcommunity.com/id/{vanity_name}/?xml=1"
        try:
            # Запрос без прокси, как и требовалось
            resp = requests.get(xml_url, timeout=5, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code == 200:
                # Ищем тег <steamID64>
                xml_match = re.search(r"<steamID64>(\d+)</steamID64>", resp.text)
                if xml_match:
                    return xml_match.group(1)
        except Exception as e:
            return None
    return None

def process_single_line(line):
    """
    Определяет тип введенной строки и возвращает SteamID64 или None.
    """
    line = line.strip()
    if not line:
        return None

    # Тип A: Это SteamID64 (начинается на 7, длина 17 цифр)
    # Простая проверка: состоит только из цифр и длина 17
    if line.isdigit() and len(line) == 17 and line.startswith("7"):
        return line

    # Тип B: Это ссылка (содержит http/https/steamcommunity)
    if "steamcommunity.com" in line or "http" in line:
        return get_steamid64_from_url(line)

    # Тип C: Это SteamID32 (остальное)
    # Считаем, что это число, но не ID64. Пытаемся сконвертировать.
    if line.isdigit():
        try:
            id32 = int(line)
            # Базовая защита от дурака (если ввели слишком маленькое число)
            if id32 > 0:
                return str(id32 + STEAM_BASELINE)
        except:
            pass
    return None

def run_manual_mode():
    """
    Основная функция UI для ручного ввода или загрузки из файла.
    """
    if not worker_instance:
        print(f"{ui.Gradient.RED}Ошибка: Воркер не инициализирован. Сначала проверьте конфиг или запустите бота.{ui.Gradient.RESET}")
        time.sleep(2)
        return

    ui.clear_console()
    print(f"{ui.Gradient.CYAN}=== РУЧНОЕ ДОБАВЛЕНИЕ ЦЕЛЕЙ ==={ui.Gradient.RESET}")
    print(f"{ui.Gradient.WHITE}Выберите режим:")
    print(f"{ui.Gradient.GREEN}1. Загрузить из файла links.txt")
    print(f"{ui.Gradient.YELLOW}2. Ручной ввод (консоль)")
    print(f"{ui.Gradient.RED}0. Назад")
    print("-" * 50)
    
    choice = input(f"{ui.Gradient.WHITE}Ваш выбор: ").strip()
    
    raw_lines = []
    
    if choice == '1':
        # Режим чтения из файла
        links_file = 'links.txt'
        if not os.path.exists(links_file):
            print(f"{ui.Gradient.RED}Файл {links_file} не найден!{ui.Gradient.RESET}")
            time.sleep(2)
            return
        
        try:
            with open(links_file, 'r', encoding='utf-8') as f:
                raw_lines = [line.strip() for line in f if line.strip()]
            
            if not raw_lines:
                print(f"{ui.Gradient.RED}Файл {links_file} пустой!{ui.Gradient.RESET}")
                time.sleep(2)
                return
                
            print(f"{ui.Gradient.GREEN}Загружено {len(raw_lines)} записей из {links_file}{ui.Gradient.RESET}")
            time.sleep(1)
            
        except Exception as e:
            print(f"{ui.Gradient.RED}Ошибка чтения файла: {e}{ui.Gradient.RESET}")
            time.sleep(2)
            return
            
    elif choice == '2':
        # Режим ручного ввода (старый код)
        ui.clear_console()
        print(f"{ui.Gradient.CYAN}=== РУЧНОЙ ВВОД ==={ui.Gradient.RESET}")
        print(f"{ui.Gradient.WHITE}Вставьте список (ID64 / ID32 / Ссылки).")
        print(f"{ui.Gradient.YELLOW}Каждая запись с новой строки.")
        print(f"{ui.Gradient.GREEN}Оставьте пустую строку и нажмите Enter для запуска.{ui.Gradient.RESET}")
        print("-" * 50)
        
        while True:
            try:
                line = input()
                if not line.strip():
                    break
                raw_lines.append(line.strip())
            except KeyboardInterrupt:
                return
                
    elif choice == '0':
        return
    else:
        return

    if not raw_lines:
        return

    print(f"\n{ui.Gradient.CYAN}--- Обработка ({len(raw_lines)} шт.) ---{ui.Gradient.RESET}")
    added_count = 0
    errors_count = 0

    for idx, raw in enumerate(raw_lines, 1):
        try:
            # Небольшая визуализация прогресса
            print(f"{ui.Gradient.WHITE}[{idx}/{len(raw_lines)}] Анализ: {raw[:30]}... ", end="")
            
            sid64 = process_single_line(raw)
            
            if sid64:
                # Добавляем в очередь воркера с флагом ignore_cache=True
                worker_instance.add_steam_id(sid64, ignore_cache=True)
                print(f"{ui.Gradient.GREEN}-> OK ({sid64}){ui.Gradient.RESET}")
                added_count += 1
            else:
                print(f"{ui.Gradient.RED}-> FAIL (Не удалось определить ID){ui.Gradient.RESET}")
                errors_count += 1
            
            # Небольшая пауза, чтобы не спамить запросами к XML API, если там Vanity URL
            if "steamcommunity.com" in raw:
                time.sleep(0.3)
                
        except Exception as e:
            print(f"{ui.Gradient.RED}-> ERROR: {e}{ui.Gradient.RESET}")
            errors_count += 1

    print("-" * 50)
    print(f"{ui.Gradient.CYAN}Итог: {ui.Gradient.GREEN}Добавлено: {added_count} {ui.Gradient.RED}Ошибок: {errors_count}{ui.Gradient.RESET}")
    print(f"{ui.Gradient.YELLOW}Задачи переданы воркеру. Они начнут выполняться, когда вы запустите бота (п.6, 7 или 8).{ui.Gradient.RESET}")
    input("\nНажмите Enter, чтобы вернуться в меню...")
