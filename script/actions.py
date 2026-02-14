import logger
import typo_generator
from clicker import click, scroll, move 
from past import type_text
from exceptions import UserInterruptError
import re
import os
import traceback
from PIL import ImageGrab, Image
import numpy as np 
from colorama import Fore, Style
import ctypes

# --- ВКЛЮЧЕНИЕ DPI AWARENESS (Для четких скриншотов на Windows) ---
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except:
        pass

# Импортируем наш улучшенный сканнер
import ocr_scanner

try:
    import cv2
    OPENCV_AVAILABLE = True
except ImportError:
    OPENCV_AVAILABLE = False
    print("Warning: OpenCV (cv2) not found. Image matching will not work.")

try:
    from web_worker import worker_instance
except ImportError:
    worker_instance = None

# --- Вспомогательные функции ---

def _get_params(config):
    coords = config['coordinates']
    timing = config['timing']
    mouse = config['mouse_movement']
    return coords, timing, mouse

def _execute_click(config, coord_name, ignore_pause=False):
    coords, timing, mouse = _get_params(config)
    target_coords = coords[coord_name]
    
    success = click(
        target_coords[0], target_coords[1], 
        timing['mouse_move_duration'], 
        mouse['smoothness_points'], 
        mouse['target_randomization_enabled'], 
        mouse['horizontal_offset'], 
        mouse['vertical_offset'],
        ignore_pause=ignore_pause
    )
    
    if not success and not ignore_pause:
        raise UserInterruptError(f"Действие '{coord_name}' прервано пользователем.")

def _execute_hover(config, coord_name):
    coords, timing, mouse = _get_params(config)
    target_coords = coords[coord_name]
    
    success = move(
        target_coords[0], target_coords[1], 
        timing['mouse_move_duration'], 
        mouse['smoothness_points'], 
        mouse['target_randomization_enabled'], 
        mouse['horizontal_offset'], 
        mouse['vertical_offset']
    )
    if not success:
        raise UserInterruptError(f"Наведение '{coord_name}' прервано.")

def click_at_coordinates(config, x, y):
    _, timing, mouse = _get_params(config)
    if not click(x, y, timing['mouse_move_duration'], mouse['smoothness_points'], mouse['target_randomization_enabled'], mouse['horizontal_offset'], mouse['vertical_offset']):
        raise UserInterruptError(f"Клик по координатам {x},{y} прерван.")

def scroll_page_down(config):
    _, _, mouse = _get_params(config)
    strength = mouse.get('scroll_strength', -300)
    if strength > 0: strength = -strength
    if not scroll(strength):
        raise UserInterruptError("Скроллинг прерван пользователем.")

# --- Логика анализа текста (OCR Logic) ---

def chinese_symbol_finder(text):
    for char in text:
        if '\u4e00' <= char <= '\u9fff': return True
        if '\u3400' <= char <= '\u4dbf': return True
    return False

def process_lobby_data(raw_lines, config):
    ocr_cfg = config.get("ocr_settings", {})
    PLAYER_COUNT_X = ocr_cfg.get("player_count_x", 1190)
    TOLERANCE = ocr_cfg.get("player_count_tolerance", 60)
    
    found_entries = []
    
    for line in raw_lines:
        full_text = line['text']
        if not chinese_symbol_finder(full_text):
            continue
            
        player_count_val = "0"
        if 'parts' in line:
            for part in line['parts']:
                part_center_x = part['x'] + (part['w'] / 2)
                if any(char.isdigit() for char in part['text']):
                    if abs(part_center_x - PLAYER_COUNT_X) < TOLERANCE:
                        player_count_val = part['text']
                        break
        
        clean_name = re.sub(r'[\d\/\s\\]+人?$', '', full_text).strip()
        center_x = int(line['x'] + (line['w'] / 2))
        center_y = int(line['y'] + (line['h'] / 2))
        
        found_entries.append({
            "text": clean_name,
            "players": player_count_val,
            "x": center_x,
            "y": center_y
        })
    return found_entries

def read_steam_id_safely(config):
    """
    Сканирует область Steam ID с использованием улучшенных параметров качества.
    """
    base_coords = config['coordinates'].get('scan_steam32_id')
    if not base_coords: return None

    # --- ЗАГРУЗКА НАСТРОЕК ИЗ КОНФИГА ---
    ocr_cfg = config.get("ocr_settings", {})
    scanner_cfg = ocr_cfg.get("steam_scanner_settings", {})

    START_ICON = scanner_cfg.get("start_icon", 'steam_icon.png')
    END_ICONS = scanner_cfg.get("end_icons", ['dota_plus.png', 'green_plus.png', 'end_icon.png'])
    
    SEARCH_PADDING = scanner_cfg.get("search_padding", 120)
    OFFSET_X = scanner_cfg.get("offset_x_start", 2)
    VERTICAL_PADDING = scanner_cfg.get("vertical_padding", 26) 
    OFFSET_END_ICON = scanner_cfg.get("end_icon_offset_x", -2) 
    DEFAULT_WIDTH = scanner_cfg.get("default_width", 160)
    
    # Ключевые параметры качества
    BINARIZATION_THRESH = scanner_cfg.get("binarization_threshold", 150) 
    SCALE_FACTOR = ocr_cfg.get("steam_id_scale", 3) 
    
    ocr_area = base_coords 
    matched_by_icon = False

    # 1. Поиск точных координат через OpenCV шаблоны (если доступны)
    if OPENCV_AVAILABLE and os.path.exists(START_ICON):
        try:
            search_x1 = max(0, base_coords[0] - SEARCH_PADDING)
            search_y1 = max(0, base_coords[1] - SEARCH_PADDING)
            search_x2 = base_coords[2] + SEARCH_PADDING
            search_y2 = base_coords[3] + SEARCH_PADDING
            
            screenshot_search = ImageGrab.grab(bbox=(search_x1, search_y1, search_x2, search_y2))
            screen_np = np.array(screenshot_search)
            screen_gray = cv2.cvtColor(screen_np, cv2.COLOR_RGB2GRAY)
            
            template_start = cv2.imread(START_ICON, 0)
            if template_start is not None:
                w_start, h_start = template_start.shape[::-1]
                res = cv2.matchTemplate(screen_gray, template_start, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(res)
                
                if max_val >= 0.8:
                    found_x = max_loc[0] + search_x1
                    found_y = max_loc[1] + search_y1
                    
                    ocr_x1 = int(found_x + w_start + OFFSET_X)
                    center_y = found_y + (h_start / 2)
                    
                    ocr_y1 = int(center_y - VERTICAL_PADDING)
                    ocr_y2 = int(center_y + VERTICAL_PADDING)
                    
                    found_end_points = []
                    for icon_name in END_ICONS:
                        if os.path.exists(icon_name):
                            template_end = cv2.imread(icon_name, 0)
                            if template_end is not None:
                                res_end = cv2.matchTemplate(screen_gray, template_end, cv2.TM_CCOEFF_NORMED)
                                _, max_v_e, _, max_l_e = cv2.minMaxLoc(res_end)
                                if max_v_e >= 0.8:
                                    found_end_x = max_l_e[0] + search_x1
                                    if found_end_x > ocr_x1:
                                        found_end_points.append(found_end_x)

                    if found_end_points:
                        ocr_x2 = int(min(found_end_points) + OFFSET_END_ICON)
                    else:
                        ocr_x2 = int(ocr_x1 + DEFAULT_WIDTH)

                    ocr_area = [ocr_x1, ocr_y1, ocr_x2, ocr_y2]
                    matched_by_icon = True
                    
        except Exception as e:
            print(f"[OpenCV Icon Search Error] {e}")

    # --- УЛУЧШЕНИЕ КАЧЕСТВА ИЗОБРАЖЕНИЯ ПЕРЕД OCR ---
    try:
        raw_screenshot = ImageGrab.grab(bbox=tuple(ocr_area))
        
        if OPENCV_AVAILABLE:
            # Превращаем в массив OpenCV
            img_cv = np.array(raw_screenshot)
            img_cv = cv2.cvtColor(img_cv, cv2.COLOR_RGB2GRAY)

            # Качественное увеличение (INTER_CUBIC дает лучшие края для OCR)
            h, w = img_cv.shape
            img_cv = cv2.resize(img_cv, (w * SCALE_FACTOR, h * SCALE_FACTOR), interpolation=cv2.INTER_CUBIC)

            # Бинаризация: убираем фон, оставляем только цифры
            # Текст в доте светлый на темном. Делаем его белым на черном фоне.
            _, img_cv = cv2.threshold(img_cv, BINARIZATION_THRESH, 255, cv2.THRESH_BINARY)

            # Инвертируем: Tesseract лучше всего читает ЧЕРНЫЙ текст на БЕЛОМ фоне
            img_cv = cv2.bitwise_not(img_cv)

            # Сохраняем итоговый результат, который пойдет в OCR
            cv2.imwrite("DEBUG_SCAN.png", img_cv)
            
            # Если сканер требует PIL объект, конвертируем обратно
            final_img = Image.fromarray(img_cv)
        else:
            raw_screenshot.save("DEBUG_SCAN.png")
            final_img = raw_screenshot

        # Вызываем OCR по уже подготовленному изображению
        # Мы отключаем внутреннее масштабирование сканера (scale_factor=1), т.к. сделали его сами
        results = ocr_scanner.scan_text_in_rect(
            ocr_area, 
            psm_mode=7, 
            languages='eng', 
            scale_factor=1, 
            whitelist='0123456789', 
            preprocessing=None, 
            binary_threshold=None
        )
        
        if results and results[0]['text']:
            return results[0]['text']
        
    except Exception as e:
        print(f"Ошибка обработки изображения/OCR: {e}")

    return None

# --- Основные действия ---

def focus_chat(config):
    _execute_click(config, 'chat_pos')

def leave_channel(config):
    _execute_click(config, 'channel_leave_pos')

def start_channel_join(config):
    _execute_click(config, 'channel_join_pos')

def select_region_category(config):
    _execute_click(config, 'channel_region_pos')

def focus_find_region_input(config):
    _execute_click(config, 'channel_find_pos')

def accept_channel(config):
    _execute_click(config, 'channel_accept_pos')

def select_normal_category(config):
    _execute_click(config, 'channel_normal_pos')

def click_filter_participants(config):
    _execute_click(config, 'channel_filter_pos')

def hover_channel_list(config):
    _execute_hover(config, 'channel_list_hover_pos')

def close_search_window(config):
    _execute_click(config, 'channel_window_close_pos')

def force_close_search_window(config):
    _execute_click(config, 'channel_window_close_pos', ignore_pause=True)

def type_region_name(region_name: str):
    type_text(region_name, press_enter=False)

def send_chinese_greeting(config):
    phrase = config['other_settings'].get('chinese_spam_phrase', 'Hello')
    timing = config['timing']
    type_text(phrase, delay_before_enter=timing['pause_before_send'], press_enter=True)

def send_spam_message(config, language: str, message_index: int):
    other_cfg = config['other_settings']
    timing = config['timing']

    if message_index == 0:
        first_phrase_dict = other_cfg['first_spam_phrase']
        if isinstance(first_phrase_dict, dict):
            phrase_text = first_phrase_dict.get(language, next(iter(first_phrase_dict.values())))
        else:
            phrase_text = str(first_phrase_dict)

        typo_cfg = config.get('typo_settings', {})
        final_phrase = typo_generator.introduce_typos(phrase_text, typo_cfg, language) if typo_cfg.get('enabled') else phrase_text
        if final_phrase != phrase_text:
            logger.log_event('typo_generated', original=phrase_text, modified=final_phrase)
    else:
        final_phrase = other_cfg['spam_phrase_template']

    type_text(final_phrase, delay_before_enter=timing['pause_before_send'], press_enter=True)

# --- Финальная функция сканирования ---

def perform_quick_scan(config):
    if worker_instance is None:
        logger.log_event('error', message="[SCAN] WebWorker не инициализирован.")
        return
    
    steam32_str = read_steam_id_safely(config)
    
    if not steam32_str:
        print(f"{Fore.RED}>>> OCR: ID не найден. Проверьте DEBUG_SCAN.png{Style.RESET_ALL}")
        return

    try:
        # Убираем лишние символы, если они проскочили
        clean_id = ''.join(filter(str.isdigit, steam32_str))
        
        if not clean_id or len(clean_id) < 5 or len(clean_id) > 12:
             print(f"{Fore.YELLOW}>>> OCR: Некорректный ID ({clean_id}){Style.RESET_ALL}")
             return

        steam32_int = int(clean_id)
        steam_base = 76561197960265728
        steam64_id = steam32_int + steam_base
        
        print(f"{Fore.GREEN}>>> УСПЕХ: {steam32_int} (Steam64: {steam64_id}){Style.RESET_ALL}")
        worker_instance.add_steam_id(steam64_id)

    except Exception as e:
        print(f"Ошибка обработки: {e}")