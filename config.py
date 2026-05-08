import os
from dataclasses import dataclass


def parse_env_bool(name, default="false"):
    return os.environ.get(name, default).lower() in ("1", "true", "yes", "on")


def parse_env_list(name):
    return {
        item.strip().upper()
        for item in os.environ.get(name, "").split(",")
        if item.strip()
    }


@dataclass(frozen=True)
class AppConfig:
    watched_folder: str
    auth_data: str
    delete_after_upload: bool
    ignored_path_patterns: set
    source_type: str

    @classmethod
    def from_env(cls, get_config):
        return cls(
            watched_folder=os.environ.get("WATCHED_FOLDER", "/data"),
            auth_data=get_config("auth_data", ""),
            delete_after_upload=parse_env_bool("DELETE_AFTER_UPLOAD"),
            ignored_path_patterns=parse_env_list("IGNORED_PATH_PATTERNS"),
            source_type=os.environ.get("SOURCE_TYPE", "filesystem").lower(),
        )
