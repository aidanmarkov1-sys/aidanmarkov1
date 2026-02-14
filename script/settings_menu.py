# --- START OF FILE settings_menu.py ---
import json
import time
import ui
from config_utils import load_config, save_config

# Обновленный словарь описаний с настройками оверлея
ALL_SETTINGS_DESCRIPTIONS = {
    "coordinates": {
        "title": "Координаты", 
        "chat_pos": "Поле ввода текста в чате", 
        "channel_leave_pos": "Кнопка 'Покинуть канал'", 
        "channel_join_pos": "Кнопка 'Добавить канал'", 
        "channel_region_pos": "Кнопка 'Региональный канал'", 
        "channel_find_pos": "Поле для ввода названия региона", 
        "channel_accept_pos": "Кнопка подтверждения вступления", 
        "channel_normal_pos": "Категория 'Обычные'", 
        "channel_filter_pos": "Фильтр участников", 
        "scan_steam32_id": "Зона сканирования SteamID", 
        "channel_list_hover_pos": "Точка наведения списка", 
        "channel_window_close_pos": "Крестик окна поиска"
    },
    "timing": {
        "title": "Временные настройки", 
        "pause_between_cycles": "Пауза между циклами (сек)", 
        "mouse_move_duration": "Базовое время движения мыши (сек)", 
        "main_cooldown": "Основной кулдаун после цикла (сек)", 
        "spam_message_delay": "Задержка между спам-сообщениями (сек)", 
        "action_delay": "Задержка между действиями (сек)", 
        "restart_hold_duration": "Время удержания клавиши перезапуска", 
        "pause_after_join": "Пауза после вступления в канал", 
        "pause_before_send": "Пауза перед отправкой сообщения", 
        "chat_unfold_delay": "Пауза на разворот чата", 
        "mixed_mode_cooldown": "Кулдаун при смене режима (Mixed)"
    },
    "mouse_movement": {
        "title": "Мышь и ввод", 
        "smoothness_points": "Количество точек плавности", 
        "target_randomization_enabled": "Включить рандомизацию (true/false)", 
        "horizontal_offset": "Макс. гор. смещение", 
        "vertical_offset": "Макс. верт. смещение", 
        "scroll_strength": "Сила скролла"
    },
    "hotkeys": {
        "title": "Горячие клавиши", 
        "start_stop_key": "Клавиша старт/стоп", 
        "scan_key": "Клавиша сканирования"
    },
    "other_settings": {
        "title": "Прочее", 
        "lzt_api_token": "API Token (LZT Market)", 
        "spam_phrases_count": "Количество шаблонных фраз", 
        "spam_phrase_template": "Шаблонная фраза", 
        "first_spam_phrase": "Основное сообщение (JSON)", 
        "show_recommendations": "Показывать рекомендации", 
        "last_selected_profile": "Последний профиль", 
        "max_players_in_lobby": "Макс игроков (OCR)", 
        "chinese_spam_phrase": "Китайская фраза", 
        "chinese_big_cooldown_multiplier": "Множитель китайского КД", 
        "close_window_on_pause": "Закрывать поиск при паузе", 
        "headless_mode": "Скрытый режим браузера"
    },
    "typo_settings": {
        "title": "Настройки опечаток", 
        "enabled": "Включить опечатки", 
        "chance": "Шанс опечатки", 
        "min_chars_between_typos": "Мин символов между опечатками"
    },
    "ocr_settings": {
        "title": "Настройки OCR (Распознавание)", 
        "scan_area": "Зона сканирования [x1, y1, x2, y2]", 
        "recovery_zone": "Зона восстановления", 
        "tesseract_languages": "Языки Tesseract", 
        "player_count_x": "Координата X столбца игроков", 
        "player_count_tolerance": "Погрешность поиска столбца", 
        "line_merge_threshold": "Порог объединения строк", 
        "steam_id_scale": "Масштаб для ID (OCR)",
        "lobby_scale": "Масштаб для Лобби (OCR)"
    },
    # --- НОВАЯ СЕКЦИЯ ---
    "overlay_settings": {
        "title": "Настройки Оверлея",
        "enabled": "Включить оверлей (true/false)",
        "overlay_rect": "Координаты [x1, y1, x2, y2]",
        "opacity": "Прозрачность окна (0.1 - 1.0)",
        "bg_color": "Цвет фона (HEX)",
        "notification_duration": "Время показа 1 сообщения (сек)",
        "window_timeout": "Время до исчезновения окна (сек)",
        "font_size": "Размер шрифта"
    }
}

def edit_settings(filter_category=None):
    config = load_config()
    param_map = {} 
    
    while True:
        ui.clear_console()
        menu_title = f"--- Меню OCR ---" if filter_category else "--- Меню общих настроек ---"
        print("\n" + ui.Gradient.YELLOW + menu_title)
        param_num = 1
        categories = list(config.keys())
        if filter_category: categories = [filter_category]

        for category_key in categories:
            if not isinstance(config.get(category_key), dict): continue
            if filter_category is None and category_key == 'ocr_settings': continue

            category_config_data = config[category_key]
            category_desc_data = ALL_SETTINGS_DESCRIPTIONS.get(category_key, {})
            category_title = category_desc_data.get('title', category_key.replace('_', ' ').capitalize())
            
            # Пропускаем, если для категории нет описания (скрытые настройки)
            if not category_desc_data: continue

            print(f"\n{ui.Gradient.LIGHT_CYAN}{category_title}\n{ui.Gradient.LIGHT_CYAN}{'-' * len(category_title)}")

            for key, current_value in category_config_data.items():
                if key == 'last_selected_profile': continue
                desc_text = category_desc_data.get(key, key)
                
                # Форматирование вывода
                if key in ['scan_area', 'overlay_rect', 'scan_steam32_id', 'recovery_zone', 'coordinates']:
                    display_str = str(current_value)
                    if isinstance(current_value, list): display_str = " ".join(map(str, current_value))
                    print(f"{ui.Gradient.WHITE}{param_num}. {desc_text} (текущее: {ui.Gradient.GREEN}{display_str}{ui.Gradient.WHITE})")
                else:
                    display_value = json.dumps(current_value, ensure_ascii=False) if isinstance(current_value, dict) else current_value
                    print(f"{ui.Gradient.WHITE}{param_num}. {desc_text} (текущее: {ui.Gradient.MEDIUM_CYAN}{display_value}{ui.Gradient.WHITE})")
                
                param_map[param_num] = (category_key, key)
                param_num += 1
                
        print(f"\n{ui.Gradient.RED}0. Назад в главное меню")
        choice = input(ui.Gradient.WHITE + "Выберите номер параметра: ")
        
        if choice == '0': break
        
        try:
            choice_num = int(choice)
            if choice_num not in param_map: 
                print(f"{ui.Gradient.RED}Неверный выбор.")
                time.sleep(1)
                continue
            
            category_key, param_key = param_map[choice_num]
            current_value = config[category_key][param_key]
            desc_text = ALL_SETTINGS_DESCRIPTIONS.get(category_key, {}).get(param_key, param_key)
            print(f"\n{ui.Gradient.YELLOW}--- Редактирование: {desc_text} ---")

            new_value_str = input(f"{ui.Gradient.WHITE}Новое значение (Enter для отмены): ")
            
            if new_value_str:
                try:
                    new_value = None
                    original_type = type(current_value)
                    
                    # Авто-определение типа данных
                    if isinstance(current_value, list):
                        parts = new_value_str.replace(',', ' ').split()
                        # Пытаемся сохранить int если это координаты
                        try:
                            new_value = [int(p) for p in parts]
                        except ValueError:
                            new_value = parts # Fallback для списков строк
                    elif original_type == bool: 
                        new_value = new_value_str.lower() in ['true', '1', 't', 'y', 'да']
                    elif original_type == dict: 
                        new_value = json.loads(new_value_str)
                    elif original_type == int: 
                        new_value = int(new_value_str)
                    elif original_type == float: 
                        new_value = float(new_value_str)
                    else: 
                        new_value = new_value_str
                    
                    config[category_key][param_key] = new_value
                    save_config(config)
                    print(f"{ui.Gradient.MEDIUM_CYAN}Сохранено!")
                    time.sleep(0.5)
                except Exception as e: 
                    print(f"{ui.Gradient.RED}Ошибка формата: {e}")
                    time.sleep(2)
        except ValueError: 
            print(f"{ui.Gradient.RED}Введите число.")
            time.sleep(1)