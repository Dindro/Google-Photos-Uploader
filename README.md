# Google Photos Uploader

This project is based on [google_photos_mobile_client](https://github.com/xob0t/google_photos_mobile_client). It watches a local folder, SMB mount, or NAS-mounted folder and automatically uploads supported media files to Google Photos from a lightweight Docker container.

---

## Features

- Uploads photos and videos to Google Photos automatically.
- Watches a folder in real time and processes new files as they appear.
- Optionally deletes local files after a successful upload.
- Can optionally delete matching items through Synology Photos API.
- Includes a real-time dashboard for upload status, speed, and logs.
- Works with local folders and network-mounted storage.
- Runs as a minimal Docker container.

---

## Requirements

- Docker and Docker Compose.
- A folder containing photos or videos.
- `AUTH_DATA` for Google Photos authentication.

---

## Docker Compose

Example `docker-compose.yml`:

```yaml
services:
  gphotos-uploader:
    build: .
    container_name: gphotos-uploader
    restart: unless-stopped
    environment:
      - WATCHED_FOLDER=/data
      - DB_FILE=/app/data/uploader.db
      - AUTH_DATA=YOUR_AUTH_DATA_HERE
      - DELETE_AFTER_UPLOAD=false
      - SYNOLOGY_PHOTOS_DELETE_ENABLED=false
      - SYNOLOGY_PHOTOS_URL=https://your-nas:5001
      - SYNOLOGY_PHOTOS_USER=
      - SYNOLOGY_PHOTOS_PASSWORD=
      - SYNOLOGY_PHOTOS_SPACE=team
      - SYNOLOGY_PHOTOS_ROOT_PATH=/
      - SYNOLOGY_PHOTOS_VERIFY_SSL=false
      - IGNORED_PATH_PATTERNS=
    volumes:
      - /path/to/your/photos:/data:z
      - ./data:/app/data:z
    ports:
      - "8080:8080"
```

Replace `/path/to/your/photos` with the photo folder on the host.

`DB_FILE` controls where the SQLite database is stored inside the container. The example stores it at `/app/data/uploader.db` and mounts `./data` from the project directory, so the database is not created inside the photo folder.

`DELETE_AFTER_UPLOAD` is `false` by default. Set it to `true`, `1`, `yes`, or `on` if you want the uploader to delete local files after a successful upload.

`IGNORED_PATH_PATTERNS` is a comma-separated list of path or filename fragments to ignore. Matching is case-insensitive. For Synology folders, a useful value is:

```yaml
IGNORED_PATH_PATTERNS=@eaDir,SYNOPHOTO_THUMB,#recycle
```

The dashboard uses the container's local time for event timestamps.

---

## Synology Photos Deletion

`SYNOLOGY_PHOTOS_DELETE_ENABLED` is optional and disabled by default. When set to `true`, the uploader logs in to Synology Photos, finds the matching item, and asks Synology Photos to delete it.

If Synology Photos deletion fails or the item is not found, the uploader does not fall back to local `os.remove`. This avoids deleting a file from disk while leaving a stale item in Synology Photos.

Synology settings:

- `SYNOLOGY_PHOTOS_URL`: DSM/Synology Photos base URL, for example `https://192.168.1.10:5001`. Do not include `/photo`.
- `SYNOLOGY_PHOTOS_USER`: Synology account username.
- `SYNOLOGY_PHOTOS_PASSWORD`: Synology account password.
- `SYNOLOGY_PHOTOS_SPACE`: `team` for Shared Space or `personal` for Personal Space.
- `SYNOLOGY_PHOTOS_ROOT_PATH`: path inside Synology Photos that maps to `WATCHED_FOLDER`.
- `SYNOLOGY_PHOTOS_VERIFY_SSL`: set to `true` only if the NAS certificate is trusted by the container.

For a personal Synology Photos library stored under `/homes/dindro/Photos`, use:

```yaml
SYNOLOGY_PHOTOS_SPACE=personal
SYNOLOGY_PHOTOS_ROOT_PATH=/
```

If Docker sees the file as `/data/2024/IMG_001.jpg` and Synology Photos sees it as `/PhoneBackup/2024/IMG_001.jpg`, use:

```yaml
SYNOLOGY_PHOTOS_ROOT_PATH=/PhoneBackup
```

---

## Manual Cleanup API

Use this endpoint from iOS Shortcuts or any HTTP client to delete local files that were already uploaded successfully:

```http
POST http://SERVER_IP:8080/api/cleanup-uploaded
```

The endpoint uses the local SQLite upload history. It processes only files whose latest local status is `Uploaded` or `Kept`, and only if the stored path is still inside `WATCHED_FOLDER`.

By default it keeps history and writes `Deleted by cleanup` after successful deletion.

To also remove that file's log rows from the database, add `purge=1`:

```http
POST http://SERVER_IP:8080/api/cleanup-uploaded?purge=1
```

Example response:

```json
{
  "status": "success",
  "checked": 3,
  "deleted": 2,
  "synology_photos_deleted": 1,
  "purge_db": false,
  "db_rows_deleted": 0,
  "skipped": [
    {
      "file": "/data/photo.jpg",
      "reason": "not found"
    }
  ],
  "errors": []
}
```

If Synology Photos deletion fails, skipped rows include a `detail` field with the API error.

---

## Getting Started

1. Open a terminal in the project directory.
2. Start the container:

   ```bash
   docker compose up -d --build
   ```

3. Open the dashboard:

   ```text
   http://localhost:8080
   ```

4. Follow logs:

   ```bash
   docker compose logs -f
   ```

---

## Getting `AUTH_DATA`

You only need to do this once to get a persistent authentication string.

### Option 1: ReVanced, No Root

1. Install Google Photos ReVanced on Android:
   - Install [GmsCore](https://github.com/ReVanced/GmsCore/releases).
   - Install a patched Google Photos APK.
2. Connect the device to your computer with ADB.
3. Run one of these commands:
   - Windows: `adb logcat | FINDSTR "auth%2Fphotos.native"`
   - Linux/macOS: `adb logcat | grep "auth%2Fphotos.native"`
4. Open Google Photos ReVanced and sign in.
5. Copy the line that starts with `androidId=...`. That full line is your `AUTH_DATA`.

---

## Updating

```bash
git pull
docker compose up -d --build
```

---

## Notes

- By default, the app does not delete local files after upload. Enable `DELETE_AFTER_UPLOAD=true` only if you want automatic cleanup.
- If you use an SMB or NAS mount, make sure the container has permission to read and, if cleanup is enabled, delete files.
- Synology Photos API support relies on Synology's internal web API and may change after DSM or Synology Photos updates.
- This project is a practical wrapper around [google_photos_mobile_client](https://github.com/xob0t/google_photos_mobile_client).
