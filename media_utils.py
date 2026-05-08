import mimetypes
import os
import time


MEDIA_EXTENSIONS = (
    '.jpg',
    '.jpeg',
    '.png',
    '.heic',
    '.webp',
    '.mp4',
    '.3gp',
    '.3gpp',
    '.wmv',
    '.mov',
    '.avi',
    '.gif',
)


def register_media_mime_types():
    mimetypes.add_type('image/webp', '.webp')
    mimetypes.add_type('video/3gpp', '.3gp')
    mimetypes.add_type('video/3gpp', '.3gpp')
    mimetypes.add_type('image/heic', '.heic')
    mimetypes.add_type('video/x-ms-wmv', '.wmv')
    mimetypes.add_type('video/quicktime', '.mov')
    mimetypes.add_type('video/x-msvideo', '.avi')


def is_ignored_path(file_path, ignored_path_patterns):
    parts = [part.upper() for part in os.path.normpath(file_path).split(os.sep) if part]
    return any(pattern in part for pattern in ignored_path_patterns for part in parts)


def is_supported_media(file_path, ignored_path_patterns):
    return (
        not is_ignored_path(file_path, ignored_path_patterns)
        and file_path.lower().endswith(MEDIA_EXTENSIONS)
    )


def get_media_info(file_path):
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
    return file_size_str, file_type


def wait_for_file_ready(file_path, checks=3, interval=2):
    last_size = -1
    stable_count = 0

    while stable_count < checks:
        if not os.path.exists(file_path):
            return False

        try:
            current_size = os.path.getsize(file_path)
        except OSError:
            return False

        if current_size == last_size and current_size > 0:
            stable_count += 1
        else:
            stable_count = 0
            last_size = current_size

        time.sleep(interval)

    return True
