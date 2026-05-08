import os
import sqlite3
from datetime import datetime, timedelta


DB_FILE = os.environ.get("DB_FILE", "/app/uploader.db")


def init_db():
    db_dir = os.path.dirname(DB_FILE)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS logs
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  time TEXT,
                  action TEXT,
                  file TEXT,
                  filesize TEXT,
                  metadata TEXT,
                  created_at TEXT)''')

    # Config table for persistent settings
    c.execute('''CREATE TABLE IF NOT EXISTS config
                 (key TEXT PRIMARY KEY, value TEXT)''')

    # Try to add columns if they don't exist in an already created table
    try:
        c.execute("ALTER TABLE logs ADD COLUMN filesize TEXT")
        c.execute("ALTER TABLE logs ADD COLUMN metadata TEXT")
    except sqlite3.OperationalError:
        pass

    try:
        c.execute("ALTER TABLE logs ADD COLUMN created_at TEXT")
    except sqlite3.OperationalError:
        pass

    c.execute('''CREATE TABLE IF NOT EXISTS stats
                 (key TEXT PRIMARY KEY, value TEXT)''')

    c.execute('''CREATE TABLE IF NOT EXISTS media_files
                 (file TEXT PRIMARY KEY,
                  status TEXT NOT NULL,
                  filesize TEXT,
                  media_type TEXT,
                  source TEXT,
                  error TEXT,
                  first_seen_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL)''')
    conn.commit()
    conn.close()


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


def load_initial_stats(stats):
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM logs WHERE action = 'Uploaded'")
        stats["total_uploads"] = c.fetchone()[0]

        # Load last 100 events to memory
        c.execute("SELECT time, action, file, filesize, metadata FROM logs ORDER BY id DESC LIMIT 100")
        stats["events"] = [
            {
                "time": row[0],
                "action": row[1],
                "file": row[2],
                "filesize": row[3],
                "metadata": row[4],
            }
            for row in c.fetchall()
        ]
        conn.close()
    except Exception as e:
        print(f"Failed to load initial stats: {e}")


def record_event(stats, action, file_path, filesize="", metadata=""):
    now = datetime.now()
    event_time = now.strftime("%H:%M:%S")
    created_at = now.isoformat(timespec="seconds")

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "INSERT INTO logs (time, action, file, filesize, metadata, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (event_time, action, file_path, filesize, metadata, created_at),
    )
    conn.commit()
    conn.close()

    # Memory state for quick update
    event = {"time": event_time, "action": action, "file": file_path, "filesize": filesize, "metadata": metadata}
    stats["events"].insert(0, event)
    stats["events"] = stats["events"][:100]
    stats["last_event_time"] = event_time

    if "Uploaded" in action:
        stats["total_uploads"] += 1
        stats["session_uploads"] += 1


def upsert_media_file(file_path, status, filesize="", media_type="", source="", error=""):
    now = datetime.now().isoformat(timespec="seconds")

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        '''
        INSERT INTO media_files
            (file, status, filesize, media_type, source, error, first_seen_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(file) DO UPDATE SET
            status = excluded.status,
            filesize = COALESCE(NULLIF(excluded.filesize, ''), media_files.filesize),
            media_type = COALESCE(NULLIF(excluded.media_type, ''), media_files.media_type),
            source = COALESCE(NULLIF(excluded.source, ''), media_files.source),
            error = excluded.error,
            updated_at = excluded.updated_at
        ''',
        (file_path, status, filesize, media_type, source, error, now, now),
    )
    conn.commit()
    conn.close()


def delete_media_file(file_path):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM media_files WHERE file = ?", (file_path,))
    deleted = c.rowcount
    conn.commit()
    conn.close()
    return deleted


def list_media_files(limit=500):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        '''
        SELECT file, status, filesize, media_type, source, error, first_seen_at, updated_at
        FROM media_files
        ORDER BY updated_at DESC
        LIMIT ?
        ''',
        (limit,),
    )
    rows = c.fetchall()
    conn.close()
    return [
        {
            "file": row[0],
            "status": row[1],
            "filesize": row[2],
            "media_type": row[3],
            "source": row[4],
            "error": row[5],
            "first_seen_at": row[6],
            "updated_at": row[7],
        }
        for row in rows
    ]


def get_cleanup_candidates():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        SELECT file, filesize, media_type, status
        FROM media_files
        WHERE status IN ('uploaded', 'kept')
          AND file IS NOT NULL
          AND file != ''
    ''')
    rows = c.fetchall()
    conn.close()
    return rows


def delete_logs_older_than(days=30):
    cutoff = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "DELETE FROM logs WHERE created_at IS NOT NULL AND created_at != '' AND created_at < ?",
        (cutoff,),
    )
    deleted = c.rowcount
    conn.commit()
    conn.close()
    return deleted


def clear_logs():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM logs")
    deleted = c.rowcount
    conn.commit()
    conn.close()
    return deleted
