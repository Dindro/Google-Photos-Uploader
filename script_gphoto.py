import os
import time
import threading
import sys
from gpmc import Client
from cleanup_service import CleanupService
from config import AppConfig
from database import (
    clear_logs as db_clear_logs,
    delete_logs_older_than,
    get_config,
    init_db,
    list_media_files,
    load_initial_stats,
    record_event,
    set_config,
    upsert_media_file,
)
from dashboard import start_server
from media_utils import (
    get_media_info,
    is_ignored_path as media_is_ignored_path,
    is_supported_media as media_is_supported_media,
    register_media_mime_types,
    wait_for_file_ready,
)
from sources import create_source
from upload_processor import PhotoHandler

register_media_mime_types()

init_db()
deleted_old_logs = delete_logs_older_than(days=30)
if deleted_old_logs:
    print(f"Deleted {deleted_old_logs} log rows older than 30 days.")
CONFIG = AppConfig.from_env(get_config)

# Global state for monitoring
stats = {
    "total_uploads": 0,
    "session_uploads": 0,
    "total_seen": 0,
    "last_event_time": None,
    "upload_speed": "0 KB/s",
    "events": []
}

load_initial_stats(stats)

seen_files = set()
seen_files_lock = threading.Lock()
LOG_CLEANUP_INTERVAL_SECONDS = 24 * 60 * 60

def add_event(action, file_path, filesize="", metadata=""):
    record_event(stats, action, file_path, filesize, metadata)


def clear_logs():
    deleted = db_clear_logs()
    stats["events"] = []
    stats["last_event_time"] = None
    stats["total_uploads"] = 0
    return {"status": "success", "deleted": deleted}


def run_periodic_log_cleanup():
    while True:
        time.sleep(LOG_CLEANUP_INTERVAL_SECONDS)
        try:
            deleted = delete_logs_older_than(days=30)
            if deleted:
                print(f"Periodic cleanup deleted {deleted} log rows older than 30 days.")
        except Exception as e:
            print(f"Periodic log cleanup failed: {e}")

def is_ignored_path(file_path):
    return media_is_ignored_path(file_path, CONFIG.ignored_path_patterns)

def is_supported_media(file_path):
    return media_is_supported_media(file_path, CONFIG.ignored_path_patterns)

def update_media_status(file_path, status, filesize="", media_type="", source_name="", error=""):
    upsert_media_file(file_path, status, filesize, media_type, source_name, error)

def mark_seen(file_path):
    normalized_path = os.path.abspath(file_path)
    with seen_files_lock:
        if normalized_path in seen_files:
            return False
        seen_files.add(normalized_path)
        return True

def unmark_seen(file_path):
    normalized_path = os.path.abspath(file_path)
    with seen_files_lock:
        seen_files.discard(normalized_path)

def process_new_file(event_handler, file_path):
    if not mark_seen(file_path):
        return
    file_size_str, file_type = get_media_info(file_path)
    update_media_status(file_path, "discovered", file_size_str, file_type, event_handler.source.name)
    if wait_for_file_ready(file_path):
        event_handler.process_file(file_path, is_initial=False)
    else:
        unmark_seen(file_path)
        update_media_status(file_path, "not_ready", file_size_str, file_type, event_handler.source.name)
        add_event("Skipped: file not ready", file_path)

# Initialize client lazily
client = None
def get_client():
    global client
    if client is None:
        if not CONFIG.auth_data:
            raise ValueError("AUTH_DATA is not configured. Please open Dashboard -> Settings.")
        client = Client(auth_data=CONFIG.auth_data)
    return client

def create_photo_handler(source):
    return PhotoHandler(
        source=source,
        stats=stats,
        delete_after_upload=CONFIG.delete_after_upload,
        is_supported_media=is_supported_media,
        is_ignored_path=is_ignored_path,
        get_media_info=get_media_info,
        update_media_status=update_media_status,
        add_event=add_event,
        get_client=get_client,
        process_new_file=process_new_file,
    )

def main():
    try:
        source = create_source(
            CONFIG,
            is_supported_media,
            is_ignored_path,
            process_new_file,
            add_event,
            get_config=get_config,
            set_config=set_config,
        )
    except ValueError as e:
        print(e)
        sys.exit(1)

    cleanup_service = CleanupService(source, CONFIG.watched_folder)

    # Start web server thread
    web_thread = threading.Thread(
        target=start_server,
        args=(
            stats,
            CONFIG.auth_data,
            set_config,
            cleanup_service.cleanup_uploaded_files,
            list_media_files,
            clear_logs,
        ),
        daemon=True
    )
    web_thread.start()

    cleanup_thread = threading.Thread(target=run_periodic_log_cleanup, daemon=True)
    cleanup_thread.start()

    # Pre-check AUTH_DATA
    if not CONFIG.auth_data:
        print("WARNING: AUTH_DATA is not set. Dashboard remains active on port 8080 for configuration.")
        # Keep the main loop running so the container does not exit.
        try:
            while True:
                time.sleep(10)
        except KeyboardInterrupt:
            sys.exit(0)

    event_handler = create_photo_handler(source)

    # Count all files at startup so progress stays accurate.
    print(f"Scanning total files in {CONFIG.watched_folder} using {source.name} source...")
    try:
        initial_files = source.scan_initial()
    except Exception as e:
        print(f"{source.name} source scan failed: {e}")
        sys.exit(1)

    for file_path in initial_files:
        mark_seen(file_path)
        file_size_str, file_type = get_media_info(file_path)
        update_media_status(file_path, "discovered", file_size_str, file_type, source.name)
    
    stats["total_seen"] = len(initial_files)
    print(f"Found {stats['total_seen']} files to process.")

    source.start(event_handler)

    # Process existing files.
    for file_path in initial_files:
        event_handler.process_file(file_path, is_initial=True)

    try:
        while True:
            time.sleep(10)
    except KeyboardInterrupt:
        source.stop()

if __name__ == "__main__":
    main()
