import json
import mimetypes
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse


def create_dashboard_handler(
    stats,
    auth_data,
    set_config,
    cleanup_uploaded_files,
    list_media_files,
    clear_logs,
):
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
            elif path == '/api/media-files':
                self.send_json(200, {"files": list_media_files()})
            elif path == '/api/config':
                self.send_json(200, {"auth_data": auth_data})
            elif path.startswith('/media/'):
                try:
                    file_path = path[1:]
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
                result = cleanup_uploaded_files()
                status_code = 409 if result["status"] == "busy" else 200
                self.send_json(status_code, result)
            elif path == '/api/logs/clear':
                result = clear_logs()
                self.send_json(200, result)
            else:
                self.send_error(404)

        def log_message(self, format, *args):
            return

    return DashboardHandler


def start_server(
    stats,
    auth_data,
    set_config,
    cleanup_uploaded_files,
    list_media_files,
    clear_logs,
    host='0.0.0.0',
    port=8080,
):
    handler = create_dashboard_handler(
        stats,
        auth_data,
        set_config,
        cleanup_uploaded_files,
        list_media_files,
        clear_logs,
    )
    server = HTTPServer((host, port), handler)
    print(f"Dashboard available on port {port}")
    server.serve_forever()
