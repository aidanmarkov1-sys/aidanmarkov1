import base64
import io
import threading
import random
import time
import json
import copy
import os
from PIL import Image, ImageGrab, ImageEnhance
from colorama import Fore, Style

import logger

try:
    from curl_cffi import requests as curl_requests
    CURL_AVAILABLE = True
except ImportError:
    import requests as curl_requests
    CURL_AVAILABLE = False

class GeminiTranslator:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(GeminiTranslator, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized: return
        self.config_loader = None
        
        self.api_key = ""
        self.user_model = "" 
        self.proxy_url = None
        self.is_ready = False
        
        self.last_request_time = 0
        self.request_lock = threading.Lock()
        self.min_delay = 4.0 
        
        self._initialized = True

    def configure(self, config_loader_func):
        self.config_loader = config_loader_func
        try:
            config = self.config_loader()
        except Exception as e:
            logger.log_error(f"[Gemini] Config Load Error: {e}")
            return
        
        trans_settings = config.get("translator_settings", {})
        self.api_key = trans_settings.get("api_key", "")
        
        proxies_list = config.get("proxies", [])
        self.proxy_url = None
        if proxies_list:
            try:
                raw_proxy = random.choice(proxies_list).strip()
                if "://" not in raw_proxy:
                    self.proxy_url = f"http://{raw_proxy}"
                else:
                    self.proxy_url = raw_proxy
                safe_log = self.proxy_url.split('@')[-1] if '@' in self.proxy_url else "HIDDEN"
                logger.log_worker(f"{Fore.YELLOW}[Gemini] Proxy: {safe_log}{Style.RESET_ALL}")
            except: pass

        if not self.api_key or "ВАШ_" in self.api_key:
            logger.log_worker(f"{Fore.RED}[Gemini] API Key missing!{Style.RESET_ALL}")
            self.is_ready = False
            return

        logger.log_worker(f"{Fore.CYAN}[Gemini] Auto-discovering models...{Style.RESET_ALL}")
        discovered_model = self._fetch_available_model()
        
        if discovered_model:
            self.user_model = discovered_model
            logger.log_worker(f"{Fore.GREEN}[Gemini] Selected Model: {self.user_model}{Style.RESET_ALL}")
            self.is_ready = True
        else:
            logger.log_worker(f"{Fore.RED}[Gemini] Failed to find ANY compatible model via API. Check Key/Proxy.{Style.RESET_ALL}")
            self.user_model = "gemini-1.5-flash"
            self.is_ready = True

    def _fetch_available_model(self):
        """
        Ищет модели. ПРИОРИТЕТ: Flash (Standard) > Pro > Flash (Lite)
        """
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={self.api_key}"
        proxies_dict = {"http": self.proxy_url, "https": self.proxy_url} if self.proxy_url else None
        
        try:
            if CURL_AVAILABLE:
                response = curl_requests.get(url, proxies=proxies_dict, impersonate="chrome120", timeout=20)
            else:
                response = curl_requests.get(url, proxies=proxies_dict, timeout=20)

            if response.status_code == 200:
                data = response.json()
                models = data.get('models', [])
                candidates = []
                for m in models:
                    name = m.get('name', '').replace('models/', '')
                    methods = m.get('supportedGenerationMethods', [])
                    if 'generateContent' in methods:
                        candidates.append(name)
                
                if not candidates: return None
                
                # === УЛУЧШЕННЫЙ ВЫБОР МОДЕЛИ ===
                
                # 1. Сначала ищем свежие Flash версии, но НЕ Lite (они умнее)
                # Например: gemini-2.0-flash, gemini-1.5-flash
                for c in candidates:
                    if "flash" in c and "lite" not in c and "legacy" not in c and "8b" not in c:
                        return c
                
                # 2. Если нет обычных, ищем Pro (они еще умнее, но медленнее)
                for c in candidates:
                    if "pro" in c and "1.5" in c: return c
                
                # 3. Если ничего нет, берем хоть что-то (Lite, 8b и т.д.)
                for c in candidates:
                    if "flash" in c: return c
                    
                return candidates[0]
            else:
                logger.log_worker(f"{Fore.RED}[Gemini] ListModels Error {response.status_code}: {response.text[:100]}{Style.RESET_ALL}")
                return None
        except Exception as e:
            logger.log_error(f"[Gemini] ListModels Exception: {e}")
            return None

    def _image_to_base64(self, image):
        try:
            image = image.convert('RGB') 
            w, h = image.size
            # Агрессивное увеличение для узких полосок чата
            if h < 400: 
                scale = 2.0
                if h < 150: scale = 3.0
                new_size = (int(w * scale), int(h * scale)) 
                image = image.resize(new_size, Image.Resampling.LANCZOS)
                
                # Резкость
                enhancer = ImageEnhance.Sharpness(image)
                image = enhancer.enhance(1.5)
        except: pass 

        try:
            image.save("translator_debug_input.png", format="PNG")
        except: pass

        buffered = io.BytesIO()
        image.save(buffered, format="PNG") 
        return base64.b64encode(buffered.getvalue()).decode("utf-8")

    def _wait_for_rate_limit(self):
        with self.request_lock:
            current_time = time.time()
            elapsed = current_time - self.last_request_time
            if elapsed < self.min_delay:
                time.sleep(self.min_delay - elapsed)
            self.last_request_time = time.time()

    def capture_and_translate(self, mode_flag=None):
        if not self.is_ready: return "Err: Not Ready"
        self._wait_for_rate_limit()

        config = self.config_loader()
        settings = config.get("translator_settings", {})
        
        # Дефолтный промпт, если в конфиге пусто
        default_prompt = "Recognize all text in the image. Translate Chinese text to Russian. Keep English text and nicknames exactly as they are. Output the full result."
        system_prompt = settings.get("prompt", default_prompt)
        
        coords = settings.get("secondary_scan_area") if mode_flag == "secondary" else settings.get("scan_area")
        if not coords or len(coords) != 4: return "Err: Bad Coords"

        try:
            x1, y1, x2, y2 = coords
            x1, x2 = min(x1, x2), max(x1, x2)
            y1, y2 = min(y1, y2), max(y1, y2)
            
            if x2 - x1 < 10 or y2 - y1 < 10: return "Err: Tiny Area"

            screenshot = ImageGrab.grab(bbox=(x1, y1, x2, y2))
            base64_image = self._image_to_base64(screenshot)
            
            payload = {
                "contents": [{"parts": [{"text": system_prompt}, {"inline_data": {"mime_type": "image/png", "data": base64_image}}]}],
                # УВЕЛИЧЕННЫЙ ЛИМИТ ТОКЕНОВ ДЛЯ ДЛИННОГО ТЕКСТА
                "generationConfig": {"temperature": 0.3, "maxOutputTokens": 2048}
            }
            
            headers = {"Content-Type": "application/json"}
            proxies_dict = {"http": self.proxy_url, "https": self.proxy_url} if self.proxy_url else None
            
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.user_model}:generateContent?key={self.api_key}"
            current_payload = copy.deepcopy(payload)

            TIMEOUT_SEC = 60 

            try:
                if CURL_AVAILABLE:
                    response = curl_requests.post(url, json=current_payload, headers=headers, proxies=proxies_dict, impersonate="chrome120", timeout=TIMEOUT_SEC)
                else:
                    response = curl_requests.post(url, json=current_payload, headers=headers, proxies=proxies_dict, timeout=TIMEOUT_SEC)
            except Exception as net_err:
                logger.log_response_dump(None, f"Trans_NetErr", stage="Network", reason=str(net_err), exception_obj=net_err)
                return "Err: Network (Timeout)"

            if response.status_code == 200:
                data = response.json()
                candidates = data.get('candidates', [])
                if not candidates:
                    if data.get('promptFeedback'): return "Err: Safety"
                    return "Err: No Candidates"
                
                parts = candidates[0].get('content', {}).get('parts', [])
                if not parts: return "Err: Empty Parts"
                
                txt = parts[0].get('text', '').strip()
                return txt if txt else "Err: Empty Text"

            else:
                logger.log_response_dump(response, f"Trans_{response.status_code}", stage="API_Error", reason=f"Model: {self.user_model}")
                err_txt = response.text[:100].replace('\n', ' ')
                logger.log_worker(f"{Fore.RED}[Gemini] Request Failed ({response.status_code}): {err_txt}{Style.RESET_ALL}")
                
                if response.status_code == 429:
                    with self.request_lock: self.last_request_time = time.time() + 10.0
                    return "Err: Rate Limit"
                
                return f"Err: Http {response.status_code}"

        except Exception as e:
            logger.log_error(f"[Gemini] CRASH: {e}")
            return "Err: Crash"

translator_instance = GeminiTranslator()