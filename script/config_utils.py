# --- START OF FILE config_utils.py ---
import json
import os
import sys
import ui  # Импортируем для красивого вывода ошибок

CONFIG_FILE = 'config.json'

def load_config():
    if not os.path.exists(CONFIG_FILE):
        print(f"{ui.Gradient.RED}Файл конфигурации {CONFIG_FILE} не найден!")
        print(f"{ui.Gradient.YELLOW}Пожалуйста, создайте config.json или восстановите его.")
        input("Нажмите Enter для выхода...")
        sys.exit(1)
    
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
    except json.JSONDecodeError:
        print(f"{ui.Gradient.RED}Ошибка чтения {CONFIG_FILE}. Файл поврежден.")
        input("Нажмите Enter...")
        sys.exit(1)

    changed = False
    if 'other_settings' not in config: config['other_settings'] = {}; changed = True
    
    # Гарантируем наличие поля токена
    if 'lzt_api_token' not in config['other_settings']:
        config['other_settings']['lzt_api_token'] = ""
        changed = True

    if changed: save_config(config)
    return config

def save_config(config):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)