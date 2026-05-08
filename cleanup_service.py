import os
import threading

from database import delete_media_file, get_cleanup_candidates


class CleanupService:
    def __init__(self, source, watched_folder):
        self.source = source
        self.watched_folder = watched_folder
        self.lock = threading.Lock()

    def is_path_inside_watched_folder(self, file_path):
        try:
            watched_root = os.path.abspath(self.watched_folder)
            target_path = os.path.abspath(file_path)
            return os.path.commonpath([watched_root, target_path]) == watched_root
        except ValueError:
            return False

    def cleanup_uploaded_files(self):
        if not self.lock.acquire(blocking=False):
            return {
                "status": "busy",
                "message": "Cleanup is already running.",
                "checked": 0,
                "deleted": 0,
                "skipped": [],
                "errors": [],
            }

        result = {
            "status": "success",
            "checked": 0,
            "deleted": 0,
            "skipped": [],
            "errors": [],
        }

        try:
            rows = get_cleanup_candidates()
            result["checked"] = len(rows)

            for file_path, filesize, metadata, action in rows:
                if not self.is_path_inside_watched_folder(file_path):
                    result["skipped"].append({
                        "file": file_path,
                        "reason": "outside watched folder",
                    })
                    continue

                try:
                    deletion_result = self.source.delete_file(file_path)
                except Exception as e:
                    result["errors"].append({
                        "file": file_path,
                        "error": str(e),
                    })
                    continue

                if deletion_result == "missing":
                    result["skipped"].append({
                        "file": file_path,
                        "reason": "not found",
                    })
                    continue

                if deletion_result == "failed":
                    result["skipped"].append({
                        "file": file_path,
                        "reason": "failed",
                    })
                    continue

                if deletion_result != "deleted":
                    result["errors"].append({
                        "file": file_path,
                        "error": f"Unexpected delete status: {deletion_result}",
                    })
                    continue

                result["deleted"] += 1
                print(f"Cleanup deleted uploaded file: {file_path}")
                delete_media_file(file_path)

            if result["errors"]:
                result["status"] = "partial_error"

            return result
        finally:
            self.lock.release()
