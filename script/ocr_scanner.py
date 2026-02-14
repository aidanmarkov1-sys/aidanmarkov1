import os
import ctypes
import pytesseract
from pytesseract import Output
from PIL import ImageGrab, Image, ImageOps, ImageEnhance
import numpy as np

# ================= СИСТЕМНЫЕ НАСТРОЙКИ (DPI FIX) =================

try:
    # Убирает "мыло" со скриншотов, если в Windows стоит масштаб > 100%
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except:
        pass

# ================= СИСТЕМНЫЕ ФУНКЦИИ =================

def get_short_path_name(long_name):
    output_buf_size = ctypes.windll.kernel32.GetShortPathNameW(long_name, None, 0)
    if output_buf_size == 0: return long_name
    output_buf = ctypes.create_unicode_buffer(output_buf_size)
    ctypes.windll.kernel32.GetShortPathNameW(long_name, output_buf, output_buf_size)
    return output_buf.value

# ================= НАСТРОЙКИ ПУТЕЙ =================

REAL_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SAFE_BASE_DIR = get_short_path_name(REAL_BASE_DIR)

TESS_DIR = os.path.join(SAFE_BASE_DIR, "tesseract")
tesseract_exe = os.path.join(TESS_DIR, "tesseract.exe")
tessdata_dir = os.path.join(TESS_DIR, "tessdata").replace("\\", "/")

if os.path.exists(os.path.join(REAL_BASE_DIR, "tesseract", "tesseract.exe")):
    pytesseract.pytesseract.tesseract_cmd = tesseract_exe

if os.path.exists(os.path.join(REAL_BASE_DIR, "tesseract", "tessdata")):
    os.environ['TESSDATA_PREFIX'] = tessdata_dir

# ================= ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =================

def _crop_at_icons(image):
    img_rgb = image.convert("RGB")
    width, height = img_rgb.size
    pixels = img_rgb.load()
    search_start_y, search_end_y = int(height * 0.1), int(height * 0.9)
    found_x = width 
    for x in range(int(width * 0.05), width):
        is_icon = False
        for y in range(search_start_y, search_end_y, 2):
            r, g, b = pixels[x, y]
            if ((r > 120 and g > 80 and b < 100) or (g > 100 and g > r + 15)): # Gold or Green
                is_icon = True; break
        if is_icon:
            found_x = max(0, x - 2)
            break
    return image.crop((0, 0, found_x, height))

# ================= ГЛАВНАЯ ФУНКЦИЯ =================

def scan_text_in_rect(rect, languages="eng", scale_factor=3, psm_mode=6, whitelist=None, preprocessing="lobby", binary_threshold=140):
    try:
        # Захват скриншота
        screenshot = ImageGrab.grab(bbox=tuple(rect))
        
        if preprocessing == 'digits':
            screenshot = _crop_at_icons(screenshot)

        w, h = screenshot.size
        if w < 5: return [] 
        
        # 1. Увеличение (BICUBIC лучше для OCR чем LANCZOS)
        screenshot = screenshot.resize((w * scale_factor, h * scale_factor), Image.Resampling.BICUBIC)
        
        # 2. Перевод в оттенки серого
        screenshot = screenshot.convert('L')

        if preprocessing == 'digits':
            # Оптимизация для цифр (Steam ID)
            screenshot = ImageOps.invert(screenshot)
            # Повышаем контраст перед бинаризацией
            enhancer = ImageEnhance.Contrast(screenshot)
            screenshot = enhancer.enhance(2.0)
            # Бинаризация
            screenshot = screenshot.point(lambda x: 0 if x < binary_threshold else 255, '1')
            psm_mode = 7 # Одна строка текста
            whitelist = "0123456789"
        elif preprocessing == 'lobby':
            screenshot = ImageOps.invert(screenshot)
            screenshot = screenshot.point(lambda x: 0 if x < 128 else 255, '1')
        else:
            screenshot = ImageOps.invert(screenshot)
            screenshot = ImageEnhance.Contrast(screenshot).enhance(2.0)

        # 3. Добавляем поля (Tesseract любит пустые границы)
        screenshot = ImageOps.expand(screenshot, border=20, fill='white')

        # Сохраняем для отладки
        # screenshot.save("debug_processed.png")

        tess_config = f'--tessdata-dir {tessdata_dir} --oem 3 --psm {psm_mode}'
        if whitelist:
            tess_config += f' -c tessedit_char_whitelist={whitelist}'

        if preprocessing == 'digits':
            text = pytesseract.image_to_string(screenshot, lang='eng', config=tess_config)
            text = "".join(filter(str.isdigit, text))
            return [{'text': text, 'conf': 100}] if text else []
            
        else:
            data = pytesseract.image_to_data(screenshot, lang=languages, config=tess_config, output_type=Output.DICT)
            raw_boxes = []
            for i in range(len(data['text'])):
                text = data['text'][i].strip()
                conf = int(data['conf'][i]) if data['conf'][i] != -1 else 0
                if not text or conf < (40 if preprocessing == 'lobby' else 30): continue
                
                raw_boxes.append({
                    'text': text,
                    'x': (data['left'][i] - 20) / scale_factor + rect[0],
                    'y': (data['top'][i] - 20) / scale_factor + rect[1],
                    'w': data['width'][i] / scale_factor,
                    'h': data['height'][i] / scale_factor,
                    'conf': conf
                })
            return _merge_lines(raw_boxes)

    except Exception as e:
        print(f"[OCR ERROR] {e}")
        return []

def _merge_lines(raw_boxes, threshold_y=15):
    if not raw_boxes: return []
    raw_boxes.sort(key=lambda b: (b['y'], b['x']))
    merged = []
    curr = None
    for box in raw_boxes:
        if curr is None:
            curr = box.copy(); curr['parts'] = [box]
            continue
        if abs(box['y'] - curr['y']) < threshold_y:
            curr['text'] += " " + box['text']
            nx = min(curr['x'], box['x'])
            curr['w'] = max(curr['x'] + curr['w'], box['x'] + box['w']) - nx
            curr['x'] = nx
            curr['parts'].append(box)
        else:
            merged.append(curr); curr = box.copy(); curr['parts'] = [box]
    if curr: merged.append(curr)
    return merged