import json
import os
import ssl
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def env_bool(name, default="false"):
    return os.environ.get(name, default).lower() in ("1", "true", "yes", "on")


SYNOLOGY_PHOTOS_URL = os.environ.get("SYNOLOGY_PHOTOS_URL", "").rstrip("/")
SYNOLOGY_PHOTOS_USER = os.environ.get("SYNOLOGY_PHOTOS_USER", "")
SYNOLOGY_PHOTOS_PASSWORD = os.environ.get("SYNOLOGY_PHOTOS_PASSWORD", "")
SYNOLOGY_PHOTOS_SPACE = os.environ.get("SYNOLOGY_PHOTOS_SPACE", "team").lower()
SYNOLOGY_PHOTOS_ROOT_PATH = os.environ.get("SYNOLOGY_PHOTOS_ROOT_PATH", "/")
SYNOLOGY_PHOTOS_VERIFY_SSL = env_bool("SYNOLOGY_PHOTOS_VERIFY_SSL")


class SynologyPhotosClient:
    def __init__(self, watched_folder):
        self.watched_folder = watched_folder
        self.sid = None
        self.folder_cache = {}
        self.folder_path_cache_by_id = {}
        self.context = None
        if not SYNOLOGY_PHOTOS_VERIFY_SSL:
            self.context = ssl._create_unverified_context()

    @property
    def browse_prefix(self):
        if SYNOLOGY_PHOTOS_SPACE == "personal":
            return "SYNO.Foto"
        return "SYNO.FotoTeam"

    def enabled(self):
        return all([
            SYNOLOGY_PHOTOS_URL,
            SYNOLOGY_PHOTOS_USER,
            SYNOLOGY_PHOTOS_PASSWORD,
        ])

    def request(self, endpoint, params, timeout=20):
        url = f"{SYNOLOGY_PHOTOS_URL}/webapi/{endpoint}"
        data = urlencode(params).encode()
        request = Request(url, data=data, method="POST")
        request.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urlopen(request, timeout=timeout, context=self.context) as response:
            return json.loads(response.read().decode())

    def api(self, api_name, method, params=None):
        if params is None:
            params = {}
        payload = {
            "api": api_name,
            "version": "1",
            "method": method,
            **params,
        }
        if self.sid:
            payload["_sid"] = self.sid
        response = self.request("entry.cgi", payload)
        if not response.get("success"):
            raise RuntimeError(f"Synology Photos API error: {response}")
        return response.get("data", {})

    def login(self):
        if self.sid:
            return
        response = self.request("auth.cgi", {
            "api": "SYNO.API.Auth",
            "version": "3",
            "method": "login",
            "account": SYNOLOGY_PHOTOS_USER,
            "passwd": SYNOLOGY_PHOTOS_PASSWORD,
        })
        if not response.get("success"):
            raise RuntimeError(f"Synology Photos login failed: {response}")
        self.sid = response.get("data", {}).get("sid")
        if not self.sid:
            raise RuntimeError("Synology Photos login did not return sid")

    def photos_folder_path(self, file_path):
        watched_root = os.path.abspath(self.watched_folder)
        file_dir = os.path.dirname(os.path.abspath(file_path))
        rel_dir = os.path.relpath(file_dir, watched_root)
        root = "/" + SYNOLOGY_PHOTOS_ROOT_PATH.strip("/")
        if root == "/":
            root = ""
        if rel_dir == ".":
            return root or "/"
        return "/" + "/".join(part for part in [root.strip("/"), rel_dir] if part)

    def list_parent_folders(self):
        data = self.api(f"{self.browse_prefix}.Browse.Folder", "list_parents")
        return data.get("list", [])

    def list_child_folders(self, folder_id):
        data = self.api(f"{self.browse_prefix}.Browse.Folder", "list", {
            "id": folder_id,
            "offset": "0",
            "limit": "5000",
        })
        return data.get("list", [])

    def list_items_with_filter(self, start_time, end_time, offset=0, limit=500):
        data = self.api(
            f"{self.browse_prefix}.Browse.Item",
            "list_with_filter",
            {
                "time": json.dumps([{"start_time": int(start_time), "end_time": int(end_time)}]),
                "offset": str(offset),
                "limit": str(limit),
                "sort_direction": "asc",
            },
        )
        return data.get("list", [])

    def list_folder_items(self, folder_id):
        offset = 0
        limit = 500
        while True:
            data = self.api(f"{self.browse_prefix}.Browse.Item", "list", {
                "folder_id": folder_id,
                "offset": str(offset),
                "limit": str(limit),
            })
            items = data.get("list", [])
            for item in items:
                yield item
            if len(items) < limit:
                break
            offset += limit

    def _iter_folder_paths(self, folder_id, relative_folder):
        self.folder_path_cache_by_id[folder_id] = relative_folder
        for folder in self.list_child_folders(folder_id):
            child_name = os.path.basename(folder.get("name", "").rstrip("/"))
            child_id = folder.get("id")
            if not child_name or child_id is None:
                continue
            child_relative = os.path.join(relative_folder, child_name) if relative_folder else child_name
            self._iter_folder_paths(child_id, child_relative)

    def ensure_folder_path_cache(self, force_refresh=False):
        if self.folder_path_cache_by_id and not force_refresh:
            return
        self.login()
        self.folder_path_cache_by_id = {}
        root_path = "/" + SYNOLOGY_PHOTOS_ROOT_PATH.strip("/")
        if root_path == "//":
            root_path = "/"
        root_folder_id = self.find_folder_id(root_path)
        self._iter_folder_paths(root_folder_id, "")

    def find_folder_id(self, folder_path):
        normalized_path = "/" + folder_path.strip("/")
        if normalized_path == "//":
            normalized_path = "/"
        if normalized_path in self.folder_cache:
            return self.folder_cache[normalized_path]

        folders = self.list_parent_folders()
        root = next((folder for folder in folders if folder.get("name") == "/"), None)
        if not root:
            root = next((folder for folder in folders if folder.get("parent") == folder.get("id")), None)
        if not root:
            raise RuntimeError("Synology Photos root folder was not found")

        if normalized_path == "/":
            self.folder_cache[normalized_path] = root["id"]
            return root["id"]

        current = root
        path_parts = [p for p in normalized_path.split("/") if p]
        for index, part in enumerate(path_parts):
            children = self.list_child_folders(current["id"])
            expected_path = "/" + "/".join(path_parts[:index + 1])
            match = next(
                (
                    child for child in children
                    if child.get("name") == expected_path or os.path.basename(child.get("name", "")) == part
                ),
                None,
            )
            if not match:
                raise RuntimeError(f"Synology Photos folder was not found: {expected_path}")
            current = match

        self.folder_cache[normalized_path] = current["id"]
        return current["id"]

    def find_item_id(self, folder_id, filename):
        for item in self.list_folder_items(folder_id):
            if item.get("filename") == filename:
                return item.get("id")
        return None

    def iter_media_file_paths(self):
        self.login()
        root_path = "/" + SYNOLOGY_PHOTOS_ROOT_PATH.strip("/")
        if root_path == "//":
            root_path = "/"
        root_folder_id = self.find_folder_id(root_path)
        yield from self._iter_media_file_paths(root_folder_id, "")

    def _iter_media_file_paths(self, folder_id, relative_folder):
        for item in self.list_folder_items(folder_id):
            filename = item.get("filename")
            if filename:
                yield os.path.join(self.watched_folder, relative_folder, filename)

        for folder in self.list_child_folders(folder_id):
            folder_name = os.path.basename(folder.get("name", "").rstrip("/"))
            folder_id = folder.get("id")
            if not folder_name or folder_id is None:
                continue
            yield from self._iter_media_file_paths(
                folder_id,
                os.path.join(relative_folder, folder_name),
            )

    def delete_item(self, item_id):
        errors = []
        for key, value in (
            ("id", json.dumps([item_id])),
            ("id", str(item_id)),
            ("unit_id", json.dumps([item_id])),
            ("unit_id", str(item_id)),
        ):
            try:
                self.api(f"{self.browse_prefix}.Browse.Item", "delete", {key: value})
                return True
            except Exception as e:
                errors.append(str(e))
        raise RuntimeError("; ".join(errors))

    def delete_file(self, file_path):
        self.login()
        folder_path = self.photos_folder_path(file_path)
        folder_id = self.find_folder_id(folder_path)
        item_id = self.find_item_id(folder_id, os.path.basename(file_path))
        if not item_id:
            return False
        return self.delete_item(item_id)

    def delete_file_with_status(self, file_path):
        if not self.enabled():
            return "disabled"

        try:
            if self.delete_file(file_path):
                print(f"Synology Photos item deleted: {file_path}")
                return "deleted"
        except Exception as e:
            print(f"Synology Photos delete failed for {file_path}: {e}")
            return "failed"

        print(f"Synology Photos item not found: {file_path}")
        return "missing"

    def list_photo_paths(self):
        if not self.enabled():
            raise RuntimeError("Synology Photos source is not configured")
        return list(self.iter_media_file_paths())

    def supports_list_with_filter(self):
        if not self.enabled():
            return False
        self.login()
        now = int(time.time())
        try:
            self.list_items_with_filter(now - 60, now, offset=0, limit=1)
            return True
        except Exception:
            return False

    def list_recent_photo_items(self, start_time, end_time):
        if not self.enabled():
            raise RuntimeError("Synology Photos source is not configured")

        self.login()
        self.ensure_folder_path_cache()

        items = []
        offset = 0
        limit = 500
        folder_cache_refreshed = False

        while True:
            page = self.list_items_with_filter(start_time, end_time, offset=offset, limit=limit)
            if not page:
                break

            for item in page:
                filename = item.get("filename")
                folder_id = item.get("folder_id")
                item_id = item.get("id")
                if not filename or folder_id is None or item_id is None:
                    continue

                relative_folder = self.folder_path_cache_by_id.get(folder_id)
                if relative_folder is None and not folder_cache_refreshed:
                    self.ensure_folder_path_cache(force_refresh=True)
                    relative_folder = self.folder_path_cache_by_id.get(folder_id)
                    folder_cache_refreshed = True
                if relative_folder is None:
                    continue

                indexed_time_raw = item.get("indexed_time")
                indexed_time_ms = int(indexed_time_raw) if indexed_time_raw is not None else int(item.get("time", 0)) * 1000

                items.append({
                    "id": int(item_id),
                    "indexed_time_ms": indexed_time_ms,
                    "file_path": os.path.join(self.watched_folder, relative_folder, filename),
                })

            if len(page) < limit:
                break
            offset += limit

        return items


synology_photos_client = None


def get_synology_photos_client(watched_folder):
    global synology_photos_client
    if synology_photos_client is None or synology_photos_client.watched_folder != watched_folder:
        synology_photos_client = SynologyPhotosClient(watched_folder)
    return synology_photos_client


def delete_file_via_synology_photos(file_path, watched_folder):
    client = get_synology_photos_client(watched_folder)
    return client.delete_file_with_status(file_path)


def list_synology_photo_paths(watched_folder):
    client = get_synology_photos_client(watched_folder)
    return client.list_photo_paths()


def synology_supports_incremental(watched_folder):
    client = get_synology_photos_client(watched_folder)
    return client.supports_list_with_filter()


def list_recent_synology_photo_items(watched_folder, start_time, end_time):
    client = get_synology_photos_client(watched_folder)
    return client.list_recent_photo_items(start_time, end_time)
