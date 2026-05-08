import os
import time

from watchdog.events import FileSystemEventHandler


class PhotoHandler(FileSystemEventHandler):
    def __init__(
        self,
        source,
        stats,
        delete_after_upload,
        is_supported_media,
        is_ignored_path,
        get_media_info,
        update_media_status,
        add_event,
        get_client,
        process_new_file,
    ):
        self.source = source
        self.stats = stats
        self.delete_after_upload = delete_after_upload
        self.is_supported_media = is_supported_media
        self.is_ignored_path = is_ignored_path
        self.get_media_info = get_media_info
        self.update_media_status = update_media_status
        self.add_event = add_event
        self.get_client = get_client
        self.process_new_file = process_new_file

    def process_file(self, file_path, is_initial=False):
        if not self.is_supported_media(file_path):
            return

        # Initial files were counted during startup, so do not increment seen again.
        if not is_initial:
            self.stats["total_seen"] += 1

        print(f"Processing file: {file_path}")

        file_size_str, file_type = self.get_media_info(file_path)

        self.update_media_status(file_path, "processing", file_size_str, file_type, self.source.name)
        self.add_event("Processing", file_path, file_size_str, file_type)

        try:
            start_time = time.time()
            file_size = os.path.getsize(file_path)

            client = self.get_client()
            output = client.upload(target=file_path, show_progress=True)

            duration = max(time.time() - start_time, 0.1)
            speed_kbps = (file_size / 1024) / duration
            if speed_kbps > 1024:
                self.stats["upload_speed"] = f"{speed_kbps/1024:.1f} MB/s"
            else:
                self.stats["upload_speed"] = f"{speed_kbps:.1f} KB/s"

            print(f"Uploaded: {output} ({self.stats['upload_speed']})")
            self.update_media_status(file_path, "uploaded", file_size_str, file_type, self.source.name)
            self.add_event("Uploaded", file_path, file_size_str, file_type)

            if self.delete_after_upload:
                deletion_result = self.source.delete_file(file_path)
                if deletion_result != "deleted":
                    raise RuntimeError(f"Source delete did not complete: {deletion_result}")
                print(f"File deleted: {file_path}")
                self.update_media_status(file_path, "deleted", file_size_str, file_type, self.source.name)
                self.add_event("Deleted", file_path, file_size_str, file_type)
            else:
                print(f"File kept after upload: {file_path}")
                self.update_media_status(file_path, "kept", file_size_str, file_type, self.source.name)
                self.add_event("Kept", file_path, file_size_str, file_type)

        except Exception as e:
            print(f"Error occurred: {e}")
            self.update_media_status(file_path, "failed", file_size_str, file_type, self.source.name, str(e))
            self.add_event(f"Failed: {str(e)[:50]}...", file_path, file_size_str, file_type)

    def on_created(self, event):
        if not event.is_directory and not self.is_ignored_path(event.src_path):
            self.process_new_file(self, event.src_path)
