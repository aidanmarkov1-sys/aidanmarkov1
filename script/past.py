# Файл: past.py (ОБНОВЛЕННАЯ ВЕРСИЯ)

import pyperclip
import pydirectinput
import time
from stop import state_manager # <<< Импортируем наш менеджер состояний

# Отключаем стандартные паузы, чтобы контролировать их вручную
pydirectinput.PAUSE = 0
# Задержка между нажатиями клавиш для стабильности
pydirectinput.KEY_DOWN_DURATION = 0.01

def interruptible_mini_sleep(duration):
    """ Локальная прерываемая пауза, чтобы не импортировать из core.py """
    start_time = time.time()
    while time.time() - start_time < duration:
        is_running, is_restarting = state_manager.get_state()
        if not is_running or is_restarting:
            return False # Возвращаем False, если пауза была прервана
        time.sleep(0.05)
    return True # Возвращаем True, если пауза завершилась успешно

# <<< ИЗМЕНЕНИЕ: Функция теперь принимает дополнительный параметр `press_enter`
def type_text(text: str, delay_before_enter: float = 0.0, press_enter: bool = True):
    """
    Вставляет текст через буфер обмена и опционально нажимает Enter.
    Каждый шаг может быть прерван.

    :param text: Текст для вставки.
    :param delay_before_enter: Настраиваемая пауза в секундах после вставки текста, но перед нажатием Enter.
    :param press_enter: Если True, нажимает Enter в конце.
    """
    try:
        # Проверяем состояние перед началом действия
        is_running, is_restarting = state_manager.get_state()
        if not is_running or is_restarting: return

        pyperclip.copy(text)
        if not interruptible_mini_sleep(0.1): return

        pydirectinput.keyDown('ctrl')
        pydirectinput.keyDown('v')
        if not interruptible_mini_sleep(0.05):
            # Если прервали, нужно отпустить зажатые клавиши
            pydirectinput.keyUp('v')
            pydirectinput.keyUp('ctrl')
            return
        
        pydirectinput.keyUp('v')
        pydirectinput.keyUp('ctrl')

        if delay_before_enter > 0:
            if not interruptible_mini_sleep(delay_before_enter):
                return

        # <<< ИЗМЕНЕНИЕ: Проверка флага перед нажатием Enter
        if press_enter:
            is_running, is_restarting = state_manager.get_state()
            if is_running and not is_restarting:
                pydirectinput.press('enter')

    except Exception as e:
        print(f"[ERROR] Ошибка при вводе текста: {e}")
        print("        Убедитесь, что игра находится в активном окне.")