import pydirectinput
import random
import time
import math
import ctypes
from stop import state_manager

pydirectinput.PAUSE = 0
MOUSEEVENTF_WHEEL = 0x0800

def human_like_move(target_x, target_y, duration, smoothness_points, randomize_target, h_offset, v_offset, ignore_pause=False):
    start_x, start_y = pydirectinput.position()

    if randomize_target:
        target_x += random.randint(-h_offset, h_offset)
        target_y += random.randint(-v_offset, v_offset)

    vec_x = target_x - start_x
    vec_y = target_y - start_y
    distance = math.hypot(vec_x, vec_y)
    
    # Если мышь уже там, ничего не делаем
    if distance < 5: return True

    offset_magnitude = random.uniform(distance * 0.2, distance * 0.5)
    perp_x = -vec_y / distance
    perp_y = vec_x / distance

    if random.choice([True, False]): offset_magnitude *= -1

    t1 = random.uniform(0.2, 0.4)
    control1_x = start_x + vec_x * t1 + perp_x * offset_magnitude * random.uniform(0.8, 1.2)
    control1_y = start_y + vec_y * t1 + perp_y * offset_magnitude * random.uniform(0.8, 1.2)

    t2 = random.uniform(0.6, 0.8)
    control2_x = start_x + vec_x * t2 + perp_x * offset_magnitude * random.uniform(0.8, 1.2)
    control2_y = start_y + vec_y * t2 + perp_y * offset_magnitude * random.uniform(0.8, 1.2)

    points = []
    if smoothness_points <= 0: smoothness_points = 1
    for i in range(smoothness_points + 1):
        t = i / smoothness_points
        ease_t = 1 - (1 - t) ** 3
        inv_t = 1 - ease_t
        x = (inv_t**3 * start_x) + (3 * inv_t**2 * ease_t * control1_x) + (3 * inv_t * ease_t**2 * control2_x) + (ease_t**3 * target_x)
        y = (inv_t**3 * start_y) + (3 * inv_t**2 * ease_t * control1_y) + (3 * inv_t * ease_t**2 * control2_y) + (ease_t**3 * target_y)
        points.append((int(x), int(y)))

    for point_x, point_y in points:
        if not ignore_pause:
            is_running, is_restarting = state_manager.get_state()
            if not is_running or is_restarting:
                return False

        pydirectinput.moveTo(point_x, point_y)
        time.sleep(duration / smoothness_points)
        
    return True

def click(x, y, move_duration, smoothness, randomize, h_offset, v_offset, ignore_pause=False):
    move_completed = human_like_move(x, y, move_duration, smoothness, randomize, h_offset, v_offset, ignore_pause)
    
    if move_completed:
        if ignore_pause:
            pydirectinput.click()
            return True
        else:
            is_running, is_restarting = state_manager.get_state()
            if is_running and not is_restarting:
                pydirectinput.click()
                return True
    return False

# --- НОВАЯ ФУНКЦИЯ ДЛЯ ПРОСТОГО ПЕРЕМЕЩЕНИЯ ---
def move(x, y, move_duration, smoothness, randomize, h_offset, v_offset, ignore_pause=False):
    """Только двигает мышь, не кликает."""
    return human_like_move(x, y, move_duration, smoothness, randomize, h_offset, v_offset, ignore_pause)

def scroll(clicks):
    is_running, is_restarting = state_manager.get_state()
    if is_running and not is_restarting:
        try:
            ctypes.windll.user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, int(clicks), 0)
            return True
        except Exception as e:
            print(f"[CLICKER] Ошибка скроллинга: {e}")
            return False
    return False