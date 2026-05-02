import os
import mimetypes
import time
import json
import threading
import sqlite3
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, timezone, timedelta
from urllib.parse import parse_qs, urlparse
from watchdog.observers.polling import PollingObserver as Observer
from watchdog.events import FileSystemEventHandler
from gpmc import Client

# Register missing mime types
mimetypes.add_type('image/webp', '.webp')
mimetypes.add_type('video/3gpp', '.3gp')
mimetypes.add_type('video/3gpp', '.3gpp')
mimetypes.add_type('image/heic', '.heic')
mimetypes.add_type('video/x-ms-wmv', '.wmv')
mimetypes.add_type('video/quicktime', '.mov')
mimetypes.add_type('video/x-msvideo', '.avi')

DB_FILE = os.environ.get("DB_FILE", "/app/data/uploader.db")
MEDIA_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.heic', '.webp', '.mp4', '.3gp', '.3gpp', '.wmv', '.mov', '.avi', '.gif')

def parse_env_list(name):
    return {
        item.strip().upper()
        for item in os.environ.get(name, "").split(",")
        if item.strip()
    }

# Database initialization
def init_db():
    db_dir = os.path.dirname(DB_FILE)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS logs 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, time TEXT, action TEXT, file TEXT, filesize TEXT, metadata TEXT)''')
    
    # Config table for persistent settings
    c.execute('''CREATE TABLE IF NOT EXISTS config
                 (key TEXT PRIMARY KEY, value TEXT)''')
    
    # Try to add columns if they don't exist in an already created table
    try:
        c.execute("ALTER TABLE logs ADD COLUMN filesize TEXT")
        c.execute("ALTER TABLE logs ADD COLUMN metadata TEXT")
    except sqlite3.OperationalError:
        pass # Columns already exist

    c.execute('''CREATE TABLE IF NOT EXISTS stats
                 (key TEXT PRIMARY KEY, value TEXT)''')
    conn.commit()
    conn.close()

init_db()

def get_config(key, default=""):
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT value FROM config WHERE key = ?", (key,))
        row = c.fetchone()
        conn.close()
        if row:
            return row[0]
    except Exception:
        pass
    return os.environ.get(key.upper(), default)

def set_config(key, value):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

# Load initial config
WATCHED_FOLDER = os.environ.get("WATCHED_FOLDER", "/data")
AUTH_DATA = get_config("auth_data", "")
DELETE_AFTER_UPLOAD = os.environ.get("DELETE_AFTER_UPLOAD", "false").lower() in ("1", "true", "yes", "on")
IGNORED_PATH_PATTERNS = parse_env_list("IGNORED_PATH_PATTERNS")

# Global state for monitoring
stats = {
    "total_uploads": 0,
    "session_uploads": 0,
    "total_seen": 0,
    "last_event_time": None,
    "upload_speed": "0 KB/s",
    "events": []
}

def load_initial_stats():
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM logs WHERE action = 'Uploaded'")
        stats["total_uploads"] = c.fetchone()[0]
        
        # Load last 100 events to memory
        c.execute("SELECT time, action, file, filesize, metadata FROM logs ORDER BY id DESC LIMIT 100")
        for row in c.fetchall():
            stats["events"].append({
                "time": row[0], "action": row[1], "file": row[2], "filesize": row[3], "metadata": row[4]
            })
        conn.close()
    except Exception as e:
        print(f"Failed to load initial stats: {e}")

load_initial_stats()

cleanup_lock = threading.Lock()

def add_event(action, file_path, filesize="", metadata=""):
    now = datetime.now(timezone(timedelta(hours=7))).strftime("%H:%M:%S")

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO logs (time, action, file, filesize, metadata) VALUES (?, ?, ?, ?, ?)", 
              (now, action, file_path, filesize, metadata))
    conn.commit()
    conn.close()

    # Memory state for quick update
    event = {"time": now, "action": action, "file": file_path, "filesize": filesize, "metadata": metadata}
    stats["events"].insert(0, event)
    stats["events"] = stats["events"][:100]
    stats["last_event_time"] = now
    
    if "Uploaded" in action:
        stats["total_uploads"] += 1
        stats["session_uploads"] += 1

def is_path_inside_watched_folder(file_path):
    try:
        watched_root = os.path.abspath(WATCHED_FOLDER)
        target_path = os.path.abspath(file_path)
        return os.path.commonpath([watched_root, target_path]) == watched_root
    except ValueError:
        return False

def is_ignored_path(file_path):
    parts = [part.upper() for part in os.path.normpath(file_path).split(os.sep) if part]
    return any(pattern in part for pattern in IGNORED_PATH_PATTERNS for part in parts)

def is_supported_media(file_path):
    return not is_ignored_path(file_path) and file_path.lower().endswith(MEDIA_EXTENSIONS)

def delete_file_with_retries(file_path, max_retries=3):
    for attempt in range(max_retries):
        try:
            os.remove(file_path)
            return
        except PermissionError:
            if attempt < max_retries - 1:
                time.sleep(0.5 * (attempt + 1))
                continue
            raise

def cleanup_uploaded_files(purge_db=False):
    if not cleanup_lock.acquire(blocking=False):
        return {
            "status": "busy",
            "message": "Cleanup is already running.",
            "checked": 0,
            "deleted": 0,
            "purge_db": purge_db,
            "db_rows_deleted": 0,
            "skipped": [],
            "errors": []
        }

    result = {
        "status": "success",
        "checked": 0,
        "deleted": 0,
        "purge_db": purge_db,
        "db_rows_deleted": 0,
        "skipped": [],
        "errors": []
    }

    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute('''
            SELECT l.file, l.filesize, l.metadata, l.action
            FROM logs l
            INNER JOIN (
                SELECT file, MAX(id) AS max_id
                FROM logs
                WHERE file IS NOT NULL AND file != ''
                GROUP BY file
            ) latest ON latest.max_id = l.id
            WHERE l.action IN ('Uploaded', 'Kept')
        ''')
        rows = c.fetchall()
        conn.close()

        result["checked"] = len(rows)

        for file_path, filesize, metadata, action in rows:
            if not is_path_inside_watched_folder(file_path):
                result["skipped"].append({
                    "file": file_path,
                    "reason": "outside watched folder"
                })
                continue

            if not os.path.exists(file_path):
                result["skipped"].append({
                    "file": file_path,
                    "reason": "not found"
                })
                continue

            try:
                delete_file_with_retries(file_path)
                result["deleted"] += 1
                print(f"Cleanup deleted uploaded file: {file_path}")
                if purge_db:
                    conn = sqlite3.connect(DB_FILE)
                    c = conn.cursor()
                    c.execute("DELETE FROM logs WHERE file = ?", (file_path,))
                    result["db_rows_deleted"] += c.rowcount
                    conn.commit()
                    conn.close()
                    stats["events"] = [event for event in stats["events"] if event["file"] != file_path]
                else:
                    add_event("Deleted by cleanup", file_path, filesize or "", metadata or "")
            except Exception as e:
                result["errors"].append({
                    "file": file_path,
                    "error": str(e)
                })

        if result["errors"]:
            result["status"] = "partial_error"

        return result
    finally:
        cleanup_lock.release()

class DashboardHandler(BaseHTTPRequestHandler):
    def send_json(self, status_code, data):
        self.send_response(status_code)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_GET(self):
        parsed_path = urlparse(self.path)
        path = parsed_path.path

        if path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            try:
                with open('index.html', 'rb') as f:
                    self.wfile.write(f.read())
            except FileNotFoundError:
                self.wfile.write(b"index.html not found")
        elif path == '/api/logs':
            self.send_json(200, stats)
        elif path == '/api/config':
            config_data = {
                "auth_data": AUTH_DATA
            }
            self.send_json(200, config_data)
        elif path.startswith('/media/'):
            try:
                file_path = path[1:] # remove leading /
                if os.path.exists(file_path):
                    self.send_response(200)
                    mime_type, _ = mimetypes.guess_type(file_path)
                    self.send_header('Content-type', mime_type or 'application/octet-stream')
                    self.end_headers()
                    with open(file_path, 'rb') as f:
                        self.wfile.write(f.read())
                else:
                    self.send_error(404)
            except Exception:
                self.send_error(500)
        elif path == '/favicon.ico':
            if os.path.exists('media/Google-Photos-Logo.png'):
                self.send_response(301)
                self.send_header('Location', '/media/Google-Photos-Logo.png')
                self.end_headers()
            else:
                self.send_error(404)
        else:
            self.send_error(404)

    def do_POST(self):
        parsed_path = urlparse(self.path)
        path = parsed_path.path
        query = parse_qs(parsed_path.query)

        if path == '/api/restart':
            self.send_json(200, {"status": "restarting"})
            print("Restart requested from dashboard. Exiting...")
            def delayed_exit():
                time.sleep(1)
                os._exit(0)
            threading.Thread(target=delayed_exit).start()
            
        elif path == '/api/config':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data)
            
            if 'auth_data' in data:
                set_config('auth_data', data['auth_data'])
                
            self.send_json(200, {"status": "success", "message": "Configuration saved. Please restart."})
        elif path == '/api/cleanup-uploaded':
            purge_db = query.get("purge", [""])[0].lower() in ("1", "true", "yes", "on")
            result = cleanup_uploaded_files(purge_db=purge_db)
            status_code = 409 if result["status"] == "busy" else 200
            self.send_json(status_code, result)
        else:
            self.send_error(404)

    def log_message(self, format, *args):
        return # Disable console logging for HTTP requests

# Initialize client lazily
client = None
def get_client():
    global client
    if client is None:
        if not AUTH_DATA:
            raise ValueError("AUTH_DATA is not configured. Please open Dashboard -> Settings.")
        client = Client(auth_data=AUTH_DATA)
    return client

class PhotoHandler(FileSystemEventHandler):
    def process_file(self, file_path, is_initial=False):
        if is_supported_media(file_path):
            # Initial files were counted during startup, so do not increment seen again.
            if not is_initial:
                stats["total_seen"] += 1
                
            print(f"Processing file: {file_path}")
            
            file_size_str = ""
            file_type = file_path.split('.')[-1].upper()
            try:
                size_bytes = os.path.getsize(file_path)
                if size_bytes < 1024 * 1024:
                    file_size_str = f"{size_bytes/1024:.1f} KB"
                else:
                    file_size_str = f"{size_bytes/(1024*1024):.1f} MB"
            except OSError:
                pass

            add_event("Processing", file_path, file_size_str, file_type)

            try:
                # Measure upload time
                start_time = time.time()
                file_size = os.path.getsize(file_path)
                
                # Upload file
                c = get_client()
                output = c.upload(target=file_path, show_progress=True)
                
                # Calculate upload speed
                duration = max(time.time() - start_time, 0.1)
                speed_kbps = (file_size / 1024) / duration
                if speed_kbps > 1024:
                    stats["upload_speed"] = f"{speed_kbps/1024:.1f} MB/s"
                else:
                    stats["upload_speed"] = f"{speed_kbps:.1f} KB/s"

                print(f"Uploaded: {output} ({stats['upload_speed']})")
                add_event("Uploaded", file_path, file_size_str, file_type)

                if DELETE_AFTER_UPLOAD:
                    # Try deleting the file with 3 attempts.
                    delete_file_with_retries(file_path)
                    print(f"File deleted: {file_path}")
                    add_event("Deleted", file_path, file_size_str, file_type)
                else:
                    print(f"File kept after upload: {file_path}")
                    add_event("Kept", file_path, file_size_str, file_type)
                        
            except Exception as e:
                print(f"Error occurred: {e}")
                add_event(f"Failed: {str(e)[:50]}...", file_path, file_size_str, file_type)

    def on_created(self, event):
        if not event.is_directory and not is_ignored_path(event.src_path):
            # Wait briefly to ensure the file has been fully written.
            time.sleep(1)
            self.process_file(event.src_path, is_initial=False)

def start_server():
    server = HTTPServer(('0.0.0.0', 8080), DashboardHandler)
    print("Dashboard available on port 8080")
    server.serve_forever()

if __name__ == "__main__":
    # Start web server thread
    web_thread = threading.Thread(target=start_server, daemon=True)
    web_thread.start()

    # Pre-check AUTH_DATA
    if not AUTH_DATA:
        print("WARNING: AUTH_DATA is not set. Dashboard remains active on port 8080 for configuration.")
        # Keep the main loop running so the container does not exit.
        try:
            while True:
                time.sleep(10)
        except KeyboardInterrupt:
            sys.exit(0)

    event_handler = PhotoHandler()
    
    # Count all files at startup so progress stays accurate.
    print(f"Scanning total files in {WATCHED_FOLDER}...")
    initial_files = []
    if os.path.exists(WATCHED_FOLDER):
        for root, dirs, files in os.walk(WATCHED_FOLDER):
            dirs[:] = [directory for directory in dirs if not is_ignored_path(os.path.join(root, directory))]
            for file in files:
                file_path = os.path.join(root, file)
                if is_supported_media(file_path):
                    initial_files.append(file_path)
    
    stats["total_seen"] = len(initial_files)
    print(f"Found {stats['total_seen']} files to process.")

    observer = Observer()
    if os.path.exists(WATCHED_FOLDER):
        try:
            observer.schedule(event_handler, WATCHED_FOLDER, recursive=True)
            observer.start()
            print(f"Monitoring started in {WATCHED_FOLDER}...")
        except Exception as e:
            print(f"Failed to start observer: {e}")
    else:
        print(f"Warning: Folder {WATCHED_FOLDER} was not found.")

    # Process existing files.
    for file_path in initial_files:
        event_handler.process_file(file_path, is_initial=True)

    try:
        while True:
            time.sleep(10)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
