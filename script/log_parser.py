import os
import re
import json
import time
import glob
import threading
import shutil
from datetime import datetime

# ... [Keep existing configuration constants] ...
LOG_DIR = 'logs'
CACHE_FILE = 'local_cache.json'
BACKUP_FILE = 'local_cache.backup'

class LogParserDaemon(threading.Thread):
    def __init__(self):
        super().__init__()
        self.name = "LogParserDaemon"
        # ... [Keep existing init logic] ...
        self.daemon = True
        self.running = True
        self.lock = threading.Lock()
        
        self.log_pattern = re.compile(
            r'^(\d{2}:\d{2}:\d{2}).*?\[WORKER\].*?\] (.*?) \| (\d+) (.*?) \|'
        )
        
        self.cache = {
            "file_status": {},
            "entries": {}
        }
        
        self.active_file_path = None
        self.active_file_cursor = 0

    # --- NEW METHOD ADDED HERE ---
    def find_entry(self, nickname):
        """
        Thread-safe lookup for a nickname in the cache.
        Returns: (price, currency, date_obj) or None
        """
        with self.lock:
            entry = self.cache["entries"].get(nickname)
            if not entry:
                return None
            
            try:
                date_obj = datetime.strptime(entry["date"], "%Y-%m-%d %H:%M:%S")
                return (entry["price"], entry["currency"], date_obj)
            except ValueError:
                return None
    # -----------------------------

    def run(self):
        # ... [Rest of the file remains unchanged] ...
        self.load_cache()
        self.scan_and_catchup()

        while self.running:
            try:
                self.tail_active_file()
                self.check_rotation()
                time.sleep(5)
            except Exception as e:
                print(f"[LogParser] Error in loop: {e}")
                time.sleep(5)

    # ... [Keep stop, load_cache, save_cache, get_log_files, extract_date_from_filename, parse_line_data, process_file, scan_and_catchup, tail_active_file, check_rotation] ...
    def stop(self):
        self.running = False

    def load_cache(self):
        # ... [Existing code] ...
        with self.lock:
            if not os.path.exists(CACHE_FILE):
                if os.path.exists(BACKUP_FILE):
                    shutil.copy2(BACKUP_FILE, CACHE_FILE)
                else:
                    return 
            
            try:
                with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.cache["file_status"].update(data.get("file_status", {}))
                    self.cache["entries"].update(data.get("entries", {}))
            except json.JSONDecodeError:
                print("[LogParser] Cache corrupted. Creating new.")
                if os.path.exists(BACKUP_FILE):
                    shutil.copy2(BACKUP_FILE, CACHE_FILE)
                    self.load_cache()

    def save_cache(self):
        # ... [Existing code] ...
        with self.lock:
            try:
                if os.path.exists(CACHE_FILE):
                    shutil.copy2(CACHE_FILE, BACKUP_FILE)
                temp_file = CACHE_FILE + '.tmp'
                with open(temp_file, 'w', encoding='utf-8') as f:
                    json.dump(self.cache, f, ensure_ascii=False, indent=2)
                os.replace(temp_file, CACHE_FILE)
            except Exception as e:
                print(f"[LogParser] Save error: {e}")

    def get_log_files(self):
        if not os.path.exists(LOG_DIR): return []
        files = glob.glob(os.path.join(LOG_DIR, "run_*.log"))
        files.sort()
        return files

    def extract_date_from_filename(self, filename):
        basename = os.path.basename(filename)
        try:
            parts = basename.split('_')
            if len(parts) >= 2: return parts[1]
        except: pass
        return datetime.now().strftime("%Y-%m-%d")

    def parse_line_data(self, line, file_date_str, filename):
        match = self.log_pattern.search(line)
        if not match: return
        time_str, nickname, price_str, currency = match.groups()
        full_dt_str = f"{file_date_str} {time_str}"
        try:
            current_dt = datetime.strptime(full_dt_str, "%Y-%m-%d %H:%M:%S")
        except ValueError: return
        if nickname in self.cache["entries"]:
            existing_dt_str = self.cache["entries"][nickname]["date"]
            try:
                existing_dt = datetime.strptime(existing_dt_str, "%Y-%m-%d %H:%M:%S")
                if current_dt <= existing_dt: return
            except ValueError: pass
        self.cache["entries"][nickname] = {
            "price": int(price_str),
            "currency": currency.strip(),
            "date": full_dt_str,
            "source_file": os.path.basename(filename)
        }

    def process_file(self, filepath, seek_start=0):
        if not os.path.exists(filepath): return 0
        file_date = self.extract_date_from_filename(filepath)
        filename = os.path.basename(filepath)
        current_pos = seek_start
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                f.seek(seek_start)
                lines = f.readlines()
                current_pos = f.tell()
                if not lines: return current_pos
                data_changed = False
                for line in lines:
                    if "[WORKER]" in line and "|" in line:
                        self.parse_line_data(line, file_date, filepath)
                        data_changed = True
                if data_changed: self.save_cache()
        except (PermissionError, OSError): pass
        return current_pos

    def scan_and_catchup(self):
        files = self.get_log_files()
        if not files: return
        latest_file = files[-1]
        for fp in files:
            fname = os.path.basename(fp)
            status = self.cache["file_status"].get(fname, "new")
            if status == "completed": continue
            if fp == latest_file:
                self.active_file_path = fp
                self.cache["file_status"][fname] = "processing"
                self.active_file_cursor = self.process_file(fp, seek_start=0)
            else:
                self.process_file(fp, seek_start=0)
                self.cache["file_status"][fname] = "completed"
        self.save_cache()

    def tail_active_file(self):
        if self.active_file_path:
            self.active_file_cursor = self.process_file(self.active_file_path, seek_start=self.active_file_cursor)

    def check_rotation(self):
        files = self.get_log_files()
        if not files: return
        latest_on_disk = files[-1]
        if self.active_file_path != latest_on_disk:
            print(f"[LogParser] Rotation detected: {os.path.basename(latest_on_disk)}")
            if self.active_file_path:
                old_name = os.path.basename(self.active_file_path)
                self.process_file(self.active_file_path, seek_start=self.active_file_cursor)
                self.cache["file_status"][old_name] = "completed"
            self.active_file_path = latest_on_disk
            self.active_file_cursor = 0
            new_name = os.path.basename(latest_on_disk)
            self.cache["file_status"][new_name] = "processing"
            self.save_cache()

# ... [Keep parser_instance, start_parser, stop_parser] ...
parser_instance = None

def start_parser():
    global parser_instance
    if parser_instance is None or not parser_instance.is_alive():
        parser_instance = LogParserDaemon()
        parser_instance.start()
        print(f"\033[92m[System] Log Parser Service запущен.\033[0m")

def stop_parser():
    global parser_instance
    if parser_instance:
        parser_instance.stop()
        parser_instance.join(timeout=2)
        parser_instance = None