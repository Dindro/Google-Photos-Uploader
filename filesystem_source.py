import os
import time

from watchdog.observers.polling import PollingObserver as Observer


class FileSystemSource:
    name = "filesystem"

    def __init__(self, watched_folder, is_supported_media, is_ignored_path):
        self.watched_folder = watched_folder
        self.is_supported_media = is_supported_media
        self.is_ignored_path = is_ignored_path
        self.observer = None

    def scan_initial(self):
        files = []
        if os.path.exists(self.watched_folder):
            for root, dirs, filenames in os.walk(self.watched_folder):
                dirs[:] = [
                    directory
                    for directory in dirs
                    if not self.is_ignored_path(os.path.join(root, directory))
                ]
                for filename in filenames:
                    file_path = os.path.join(root, filename)
                    if self.is_supported_media(file_path):
                        files.append(file_path)
        return files

    def start(self, event_handler):
        self.observer = Observer()
        if os.path.exists(self.watched_folder):
            try:
                self.observer.schedule(event_handler, self.watched_folder, recursive=True)
                self.observer.start()
                print(f"Filesystem monitoring started in {self.watched_folder}...")
            except Exception as e:
                print(f"Failed to start observer: {e}")
        else:
            print(f"Warning: Folder {self.watched_folder} was not found.")

    def stop(self):
        if self.observer:
            self.observer.stop()
            self.observer.join()

    def delete_file(self, file_path, max_retries=3):
        for attempt in range(max_retries):
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    return "deleted"
                return "missing"
            except FileNotFoundError:
                return "missing"
            except PermissionError:
                if attempt < max_retries - 1:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                return "failed"
            except OSError:
                return "failed"
