from filesystem_source import FileSystemSource
from synology_photos_source import SynologyPhotosSource


def create_source(
    config,
    is_supported_media,
    is_ignored_path,
    process_new_file,
    record_error,
    get_config=None,
    set_config=None,
):
    if config.source_type == "synology_photos":
        return SynologyPhotosSource(
            config.watched_folder,
            is_supported_media,
            process_new_file,
            record_error,
            get_config=get_config,
            set_config=set_config,
        )
    if config.source_type == "filesystem":
        return FileSystemSource(config.watched_folder, is_supported_media, is_ignored_path)
    raise ValueError(f"Unknown SOURCE_TYPE: {config.source_type}")
