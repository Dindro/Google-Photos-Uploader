import os
import threading
import time

from synology_photos import (
    get_synology_photos_client,
    list_recent_synology_photo_items,
    list_synology_photo_paths,
)


def parse_env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return int(default)


class SynologyPhotosSource:
    name = "synology_photos"

    def __init__(
        self,
        watched_folder,
        is_supported_media,
        process_new_file,
        record_error,
        get_config=None,
        set_config=None,
    ):
        self.watched_folder = watched_folder
        self.poll_interval = parse_env_int("SYNOLOGY_PHOTOS_POLL_INTERVAL", 15)
        self.overlap_seconds = parse_env_int("SYNOLOGY_PHOTOS_OVERLAP_SECONDS", 300)
        self.is_supported_media = is_supported_media
        self.process_new_file = process_new_file
        self.record_error = record_error
        self.stop_event = threading.Event()
        self.thread = None
        self.get_config = get_config
        self.set_config = set_config
        self.watermark_key = "synology_last_indexed_time_ms"
        self.watermark_ms = self._load_watermark_ms()

    def scan_initial(self):
        return self.scan()

    def scan(self):
        return [
            file_path
            for file_path in list_synology_photo_paths(self.watched_folder)
            if self.is_supported_media(file_path)
        ]

    def _load_watermark_ms(self):
        if not self.get_config:
            return 0
        raw = self.get_config(self.watermark_key, "0")
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            return 0

    def _save_watermark_ms(self, value):
        if value <= self.watermark_ms:
            return
        self.watermark_ms = value
        if self.set_config:
            self.set_config(self.watermark_key, str(value))

    def scan_incremental(self):
        end_time = int(time.time())
        start_time = max(0, int(self.watermark_ms / 1000) - self.overlap_seconds)
        recent_items = list_recent_synology_photo_items(self.watched_folder, start_time, end_time)

        max_indexed_time_ms = self.watermark_ms
        files = []
        for item in recent_items:
            indexed_time_ms = int(item.get("indexed_time_ms", 0))
            if indexed_time_ms > max_indexed_time_ms:
                max_indexed_time_ms = indexed_time_ms

            file_path = item.get("file_path")
            if file_path and self.is_supported_media(file_path):
                files.append(file_path)

        self._save_watermark_ms(max_indexed_time_ms)
        return files

    def start(self, event_handler):
        self.thread = threading.Thread(target=self.poll, args=(event_handler,), daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=5)

    def delete_file(self, file_path):
        client = get_synology_photos_client(self.watched_folder)
        try:
            result = client.delete_file_with_status(file_path)
            if result == "disabled":
                # For Synology source, never fall back to local filesystem deletion.
                return "failed"
            if result in ("deleted", "missing", "failed"):
                return result
            return "failed"
        except Exception:
            return "failed"

    def poll(self, event_handler):
        print(f"Synology Photos incremental polling started every {self.poll_interval}s...")
        while not self.stop_event.is_set():
            try:
                file_batch = self.scan_incremental()
                for file_path in file_batch:
                    self.process_new_file(event_handler, file_path)
            except Exception as e:
                print(f"Synology Photos polling failed: {e}")
                self.record_error(f"Synology poll failed: {str(e)[:40]}...", self.watched_folder)

            self.stop_event.wait(self.poll_interval)
