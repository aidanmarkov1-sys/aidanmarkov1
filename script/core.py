# --- START OF FILE core.py ---

import logger
import logging
import time
import json
import actions
import re
import traceback
from randomizer import get_random_coefficient
from stop import state_manager
from exceptions import UserInterruptError

# Безопасный импорт OCR (оставляем для совместимости)
try:
    import ocr_scanner
    OCR_AVAILABLE = True
except ImportError:
    ocr_scanner = None
    OCR_AVAILABLE = False

logger.setup_logging(logging.INFO)

class ResumeSignal(Exception):
    pass

def load_config():
    try:
        with open('config.json', 'r', encoding='utf-8') as f: return json.load(f)
    except Exception:
        logging.error("Ошибка загрузки config.json")
        return {}

def load_profile(profile_path):
    with open(profile_path, 'r', encoding='utf-8') as f: return json.load(f)

class BaseWorker:
    def __init__(self, mixed_mode=False):
        self.config = load_config()
        self.timing = self.config['timing']
        self.other_cfg = self.config['other_settings']
        self.action_delay = self.timing['action_delay']
        self.chat_unfold_delay = self.timing.get('chat_unfold_delay', 0.2)
        
        self.spam_messages_sent = 0
        self.on_pause_callback = None
        self.mixed_mode = mixed_mode

    def _interruptible_sleep(self, duration):
        if duration <= 0: return
        start_time = time.time()
        while time.time() - start_time < duration:
            self._check_state()
            time.sleep(0.05)

    def _check_state(self):
        is_running, is_restarting = state_manager.get_state()
        if is_restarting:
            state_manager.set_restarting(False)
            raise UserInterruptError("RESTART_SIGNAL")
        
        if not is_running:
            logging.info("[CORE] Пауза активирована.")
            if self.on_pause_callback:
                try: self.on_pause_callback()
                except Exception as e: logging.error(f"Ошибка callback паузы: {e}")
            while not is_running:
                time.sleep(0.1)
                is_running, is_restarting = state_manager.get_state()
                if is_restarting:
                    state_manager.set_restarting(False)
                    raise UserInterruptError("RESTART_SIGNAL")
            logging.info("[CORE] Возобновление работы.")
            actions.focus_chat(self.config)
            return True
        return False

    def _send_spam_sequence(self, language="RU", start_index=0):
        total_messages = self.other_cfg.get('spam_phrases_count', 3) + 1
        for i in range(start_index, total_messages):
            actions.send_spam_message(self.config, language, i)
            self.spam_messages_sent += 1
            self._interruptible_sleep(self.timing['spam_message_delay'] * get_random_coefficient())

# --- CLASSIC BOT ---
class BotWorker(BaseWorker):
    def __init__(self, profile_path, mixed_mode=False):
        super().__init__(mixed_mode)
        self.profile = load_profile(profile_path)
        self.item_index = 0
        self.skip_join_pause_on_resume = False
        self.halve_next_cooldown = False

    def _process_region(self, region_data):
        region_name, language = region_data['region'], region_data['language']
        if self.spam_messages_sent == 0:
            logger.log_event('region_start', index=self.item_index + 1, total=len(self.profile), name=region_name.upper(), lang=language)
        
        actions.start_channel_join(self.config)
        self._interruptible_sleep(self.action_delay)
        actions.select_region_category(self.config)
        self._interruptible_sleep(self.action_delay)
        actions.focus_find_region_input(self.config)
        self._interruptible_sleep(self.action_delay)
        actions.type_region_name(region_name)
        self._interruptible_sleep(self.action_delay)
        actions.accept_channel(self.config)
        
        if not self.skip_join_pause_on_resume:
            self._interruptible_sleep(self.timing['pause_after_join'])
        self.skip_join_pause_on_resume = False 
        
        actions.focus_chat(self.config)
        self._interruptible_sleep(self.chat_unfold_delay)
        self._send_spam_sequence(language, start_index=self.spam_messages_sent)
        
        actions.leave_channel(self.config)
        self._interruptible_sleep(self.action_delay)
        self.spam_messages_sent = 0

    def run(self):
        try:
            logging.info(f"[CORE] Запуск классического режима.")
            actions.focus_chat(self.config)
            while self.item_index < len(self.profile):
                try:
                    self._check_state()
                    current_item = self.profile[self.item_index]
                    if isinstance(current_item, dict) and current_item.get('action') == 'big_cooldown':
                        if self.mixed_mode: return 
                        duration = float(current_item.get('duration', 0))
                        self._interruptible_sleep(duration)
                        self.item_index += 1
                        continue
                    self._process_region(current_item)
                    self.item_index += 1
                except UserInterruptError as e:
                    if str(e) == "RESTART_SIGNAL":
                        if self.mixed_mode: raise e
                        self.item_index = 0
                        continue
            logging.info("Цикл профиля завершен.")
        except Exception as e:
            if not isinstance(e, UserInterruptError): logging.error(f"Ошибка: {e}")

# --- TURBO OCR BOT (BLIND CLICKER) ---
class OCRBotWorker(BaseWorker):
    def __init__(self, mixed_mode=False):
        super().__init__(mixed_mode)
        logging.info("[TURBO] Инициализация Turbo-режима (Blind Clicker).")
        self.visited_channels = set()
        self.on_pause_callback = self._on_pause_action
        self.is_search_window_open = False
        
        # Координаты сетки (X фиксирован, Y меняется для 10 строк)
        self.FIXED_X = 960
        self.GRID_Y = [405, 435, 465, 495, 525, 555, 585, 615, 645, 675]

    def _on_pause_action(self):
        if self.other_cfg.get('close_window_on_pause', False) and self.is_search_window_open:
            actions.force_close_search_window(self.config)
            self.is_search_window_open = False

    def _check_state(self):
        was_paused = super()._check_state()
        if was_paused: raise ResumeSignal("Resumed")
        return was_paused

    def _run_scan_logic(self):
        """Мгновенно возвращает виртуальные цели без использования OCR."""
        targets = []
        for y in self.GRID_Y:
            targets.append({
                'text': f"Row_{y}", 
                'players': "0/0", # Игнорируется
                'x': self.FIXED_X, 
                'y': y
            })
        return targets

    def _setup_ui_and_scroll(self):
        actions.focus_chat(self.config)
        self._interruptible_sleep(self.action_delay)
        actions.start_channel_join(self.config)
        self.is_search_window_open = True 
        self._interruptible_sleep(self.action_delay)
        actions.select_normal_category(self.config)
        self._interruptible_sleep(self.action_delay)
        actions.click_filter_participants(self.config)
        self._interruptible_sleep(self.action_delay)
        self._interruptible_sleep(0.5) 

    def run(self):
        logging.info(f"[CORE] Запуск TURBO режима.")
        try: self._setup_ui_and_scroll()
        except (UserInterruptError, ResumeSignal): pass

        while True:
            try:
                self._check_state()
                targets = self._run_scan_logic()
                processed_in_this_batch = 0

                for target in targets:
                    self._check_state()
                    channel_id = target['text']
                    
                    if channel_id in self.visited_channels: continue 
                    
                    logging.info(f"[TURBO] Клик по строке Y: {target['y']}")
                    
                    actions.click_at_coordinates(self.config, target['x'], target['y'])
                    self._interruptible_sleep(self.action_delay)
                    actions.accept_channel(self.config)
                    self.is_search_window_open = False 
                    
                    self._interruptible_sleep(self.timing['pause_after_join'])
                    actions.focus_chat(self.config)
                    self._interruptible_sleep(self.chat_unfold_delay)
                    
                    # Отправка сообщений
                    if self.spam_messages_sent == 0:
                        actions.send_chinese_greeting(self.config)
                        self._interruptible_sleep(self.timing['spam_message_delay'])
                    
                    invite_count = self.other_cfg.get('spam_phrases_count', 3)
                    while self.spam_messages_sent < invite_count:
                        self._check_state()
                        actions.send_spam_message(self.config, "EN", 1) 
                        self.spam_messages_sent += 1
                        self._interruptible_sleep(self.timing['spam_message_delay'])
                    
                    actions.leave_channel(self.config)
                    self._interruptible_sleep(self.action_delay)
                    
                    self.spam_messages_sent = 0
                    self.visited_channels.add(channel_id)
                    processed_in_this_batch += 1
                    
                    # Если в Mixed Mode — выходим после одного успешного захода
                    if self.mixed_mode:
                        logging.info("[MIXED] Турбо-цикл завершен.")
                        return

                    self._setup_ui_and_scroll()

                # Если все 10 точек прокликаны — скроллим и сбрасываем список посещенных
                if processed_in_this_batch == 0 or len(self.visited_channels) >= 10:
                    logging.info("[TURBO] Сетка пройдена. Скролл вниз.")
                    actions.scroll_page_down(self.config)
                    self.visited_channels.clear()
                    self._interruptible_sleep(0.5)

            except ResumeSignal:
                logging.info("[TURBO] Сброс после паузы.")
                self.is_search_window_open = False 
                self.spam_messages_sent = 0
                try: self._setup_ui_and_scroll()
                except: pass
                continue

            except UserInterruptError as e:
                if str(e) == "RESTART_SIGNAL":
                    if self.mixed_mode: raise e
                    self.visited_channels.clear()
                    self.is_search_window_open = False
                    try: self._setup_ui_and_scroll()
                    except: pass
                continue
            except Exception as e:
                logging.error(f"Ошибка Turbo-цикла: {e}")
                time.sleep(2)

# --- Вспомогательные функции цикла ---
def main_cycle(profile_path):
    try: BotWorker(profile_path).run()
    except Exception: logging.error(traceback.format_exc())

def run_ocr_cycle():
    try: OCRBotWorker().run()
    except Exception as e: logging.error(traceback.format_exc())

def run_mixed_cycle(profile_path):
    logging.info("=== START MIXED MODE (TURBO) ===")
    
    def smart_sleep(duration):
        start = time.time()
        while time.time() - start < duration:
            is_running, is_restarting = state_manager.get_state()
            if is_restarting: raise UserInterruptError("RESTART_SIGNAL")
            if not is_running:
                while not is_running:
                    time.sleep(0.1)
                    is_running, _ = state_manager.get_state()
                return 
            time.sleep(0.1)
    
    while True:
        try:
            current_config = load_config()
            mixed_delay = current_config['timing'].get('mixed_mode_cooldown', 15.0)

            logging.info(">>> STEP 1: CLASSIC")
            BotWorker(profile_path, mixed_mode=True).run()
            
            smart_sleep(mixed_delay)

            logging.info(">>> STEP 2: TURBO CLICKER")
            OCRBotWorker(mixed_mode=True).run()

            smart_sleep(mixed_delay)

        except UserInterruptError as e:
             if str(e) == "RESTART_SIGNAL":
                state_manager.set_restarting(False)
                time.sleep(2.0)
                continue