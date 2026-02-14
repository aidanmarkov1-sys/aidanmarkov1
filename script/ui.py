import os
from colorama import init, Fore, Style

# Инициализация colorama
init(autoreset=True)

UI_WIDTH = 100

class Gradient:
    # Специальные цвета для градиента заголовка
    DARKEST_BLUE = Fore.BLUE
    DARK_BLUE = Fore.BLUE + Style.BRIGHT
    MEDIUM_CYAN = Fore.CYAN
    LIGHT_CYAN = Fore.CYAN + Style.BRIGHT
    LIGHTEST = Fore.WHITE + Style.BRIGHT
    MIXED_COLOR = Fore.CYAN + Style.BRIGHT
    
    # Алиасы стандартных цветов для использования в других модулях
    RED = Fore.RED
    YELLOW = Fore.YELLOW
    GREEN = Fore.GREEN
    WHITE = Fore.WHITE
    CYAN = Fore.CYAN
    MAGENTA = Fore.MAGENTA  # <--- Добавлено
    BLUE = Fore.BLUE        # <--- Добавлено для полноты
    
    # Стили
    RESET = Style.RESET_ALL
    BRIGHT = Style.BRIGHT

def clear_console():
    os.system('cls' if os.name == 'nt' else 'clear')

def print_header():
    ascii_art = r"""
 ____    __  __  ____    ____                                                         
/\  _`\ /\ \/\ \/\  _`\ /\  _`\                                                       
\ \,\L\_\ \ \_\ \ \ \L\_\ \ \L\_\    ____  _____      __      ___ ___      __   _ __  
 \/_\__ \\ \  _  \ \  _\L\ \ \L_L   /',__\/\ '__`\  /'__`\  /' __` __`\  /'__`\/\`'__\
   /\ \L\ \ \ \ \ \ \ \L\ \ \ \/, \/\__, `\ \ \L\ \/\ \L\.\_/\ \/\ \/\ \/\  __/\ \ \/ 
   \ `\____\ \_\ \_\ \____/\ \____/\/\____/\ \ ,__/\ \__/.\_\ \_\ \_\ \_\ \____\\ \_\ 
    \/_____/\/_/\/_/\/___/  \/___/  \/___/  \ \ \/  \/__/\/_/\/_/\/_/\/_/\/____/ \/_/ 
                                             \ \_\                                    
                                              \/_/                                    
"""
    lines = ascii_art.splitlines()
    colors = [
        Gradient.DARKEST_BLUE, 
        Gradient.DARKEST_BLUE, 
        Gradient.DARK_BLUE, 
        Gradient.DARK_BLUE, 
        Gradient.MEDIUM_CYAN, 
        Gradient.MEDIUM_CYAN, 
        Gradient.LIGHT_CYAN, 
        Gradient.LIGHT_CYAN, 
        Gradient.LIGHTEST, 
        Gradient.LIGHTEST
    ]
    
    start_idx = 1 if lines[0].strip() == "" else 0
    
    for i, line in enumerate(lines[start_idx:], 0):
        centered = line.center(UI_WIDTH) if len(line) < UI_WIDTH else line
        if i < len(colors): 
            print(colors[i] + centered)
        else:
            print(Gradient.LIGHTEST + centered)
    
    left_text = "   спам-бот"
    right_text = "создатель Klopo   "
    padding = UI_WIDTH - len(left_text) - len(right_text)
    if padding < 0: padding = 1
    
    print(f"{Gradient.DARK_BLUE}{left_text}{' ' * padding}{right_text}")
    print(Style.BRIGHT + Gradient.MEDIUM_CYAN + "=" * UI_WIDTH)
    print(Gradient.LIGHT_CYAN + "Добро пожаловать в панель управления".center(UI_WIDTH))
    print(Style.BRIGHT + Gradient.MEDIUM_CYAN + "=" * UI_WIDTH)

def print_recommendations():
    print("\n" + Fore.RED + "--- Рекомендации ---")
    recommendations = [
        "Версия скрипта 1.4 (Final).", 
        "F5 (Fast Scan) - сканирует SteamID справа от статуса.", 
        "Браузер закрывается автоматически при выходе (0)."
    ]
    for rec in recommendations: 
        print(f"• {rec}")
    print(Fore.RED + "-" * 30)

def print_status_panel(is_running, mode, selected_profile, hotkey, scan_key):
    status_text = "РАБОТАЕТ" if is_running else "НА ПАУЗЕ"
    mode_map = {"CLASSIC": "КЛАССИКА", "OCR": "OCR (СКАНЕР)", "MIXED": "СМЕШАННЫЙ"}
    mode_text = mode_map.get(mode, mode)
    
    print("\n" + Fore.WHITE + Style.BRIGHT + f"--- РЕЖИМ: {mode_text} ---".center(UI_WIDTH))
    if mode in ["CLASSIC", "MIXED"] and selected_profile:
        print(f"  Профиль: {Gradient.MEDIUM_CYAN}{os.path.basename(selected_profile)}")
    
    status_color = Fore.GREEN if is_running else Fore.YELLOW
    print(f"  Статус: {status_color}{status_text}{Style.RESET_ALL}")
    print("-" * UI_WIDTH)
    print(f"  Start/Pause: [{hotkey}] | Restart (Hold): [{hotkey}]".center(UI_WIDTH))
    print(f"  Fast Scan:   [{scan_key}] (Работает всегда)".center(UI_WIDTH))