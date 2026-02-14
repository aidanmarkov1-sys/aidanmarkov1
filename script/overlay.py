# --- START OF FILE overlay.py ---
import tkinter as tk
from tkinter import font as tkfont
import threading
import queue
import time
import ctypes

# Константы Win32 API для прозрачности кликов
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x80000
WS_EX_TRANSPARENT = 0x20

class OverlayController(threading.Thread):
    def __init__(self, config_loader_func, message_queue):
        super().__init__()
        self.config_loader = config_loader_func
        self.queue = message_queue
        self.daemon = True
        self.root = None
        self.labels = []
        self.last_activity_time = time.time()
        self.is_visible = False
        self.running = True

    def run(self):
        self.root = tk.Tk()
        self._setup_window()
        self._check_queue_loop()
        self.root.mainloop()

    def _setup_window(self):
        config = self.config_loader()
        settings = config.get("overlay_settings", {})
        
        coords = settings.get("overlay_rect", [10, 10, 300, 300])
        try:
            x1, y1, x2, y2 = coords
            width = x2 - x1
            height = y2 - y1
            if height <= 0: height = 300
            if width <= 0: width = 300
        except:
            x1, y1 = 10, 10
            width, height = 300, 400

        self.root.geometry(f"{width}x{height}+{x1}+{y1}")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        
        opacity = settings.get("opacity", 0.5)
        self.root.attributes("-alpha", opacity)
        
        bg_color = settings.get("bg_color", "#121212")
        self.root.configure(bg=bg_color)

        if ctypes.windll:
            try:
                hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
                style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                style = style | WS_EX_LAYERED | WS_EX_TRANSPARENT
                ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
            except Exception as e:
                print(f"[Overlay] Warning: Click-through not supported: {e}")

        self.root.withdraw()
        self.is_visible = False

    def _get_color_by_price(self, price):
        if price >= 150000: return "#FFD700" # Gold
        elif 50000 <= price < 150000: return "#FF6B6B" # Red-ish
        else: return "#00FF7F" # Green (как в логе) или White

    def add_notification(self, text, price=0, msg_type="price"):
        """
        msg_type: 'price', 'translation', 'panic', 'scanning', 'cache_fail', 'retry', 'not_found', 'system'
        """
        if not self.root: return
        
        config = self.config_loader()
        settings = config.get("overlay_settings", {})
        trans_settings = config.get("translator_settings", {})
        
        if not self.is_visible:
            self.root.deiconify()
            self.is_visible = True
        
        self.last_activity_time = time.time()
        
        bg_color = settings.get("bg_color", "#121212")
        base_size = settings.get("font_size", 12)
        
        # Defaults
        color = "#FFFFFF"
        f_size = base_size
        duration = settings.get("notification_duration", 3.0)
        family = "Verdana"
        weight = "normal"

        # --- СТИЛИЗАЦИЯ ---
        if msg_type == "panic":
            color = "#FF0000"
            f_size = base_size + 2
            duration = 10.0 
            weight = "bold"
        
        elif msg_type == "translation":
            color = trans_settings.get("text_color", "#00FF7F")
            f_size = trans_settings.get("font_size", 10)
            duration = trans_settings.get("overlay_duration", 15.0)
            family = "Segoe UI"
        
        elif msg_type == "scanning":
            color = "#00BFFF" # Deep Sky Blue
            f_size = base_size
            duration = 5.0

        elif msg_type == "cache_fail":
            color = "#FFFFFF" # White
            f_size = base_size
            duration = 3.0
            
        elif msg_type == "retry":
            color = "#FFD700" # Gold/Yellow
            f_size = base_size
            weight = "bold"
            duration = 4.0
            
        elif msg_type == "not_found":
            color = "#FF4500" # Orange Red
            f_size = base_size
            weight = "bold"
            duration = 4.0

        elif msg_type == "system":
            color = "#00FFFF" # Cyan / Aqua
            f_size = base_size
            weight = "bold"
            duration = 4.0
            family = "Segoe UI"

        else:
            # PRICE / DEFAULT
            color = self._get_color_by_price(price)
            f_size = base_size
            duration = settings.get("notification_duration", 3.0)

        font_style = tkfont.Font(family=family, size=f_size, weight=weight)
        
        coords = settings.get("overlay_rect", [10, 10, 300, 300])
        win_width = (coords[2] - coords[0])
        wrap_len = win_width - 15 

        lbl = tk.Label(
            self.root, 
            text=text, 
            fg=color, 
            bg=bg_color,
            font=font_style,
            wraplength=wrap_len,
            justify="left",
            anchor="w"
        )
        
        lbl.pack(side="top", fill="x", padx=5, pady=2)
        self.labels.append(lbl)

        # Таймер исчезновения
        self.root.after(int(duration * 1000), lambda l=lbl: self._remove_label(l))
        
        self.root.update_idletasks()
        win_height = coords[3] - coords[1]
        
        while True:
            current_content_height = sum([l.winfo_reqheight() + 4 for l in self.labels])
            if current_content_height > win_height and self.labels:
                oldest = self.labels.pop(0)
                oldest.destroy()
            else:
                break

    def _remove_label(self, label):
        try:
            if label in self.labels:
                self.labels.remove(label)
            label.destroy()
        except:
            pass

    def _check_queue_loop(self):
        try:
            while not self.queue.empty():
                msg_data = self.queue.get_nowait()
                m_type = msg_data.get('type', 'price')
                self.add_notification(
                    msg_data.get('text', ''), 
                    msg_data.get('price', 0),
                    msg_type=m_type
                )
        except queue.Empty:
            pass
            
        config = self.config_loader()
        win_timeout = config.get("overlay_settings", {}).get("window_timeout", 6.0)
        
        if self.is_visible and not self.labels:
            if time.time() - self.last_activity_time > win_timeout:
                self.root.withdraw()
                self.is_visible = False
        
        if self.running:
            self.root.after(100, self._check_queue_loop)

    def stop(self):
        self.running = False
        if self.root:
            self.root.quit()