import os
from pathlib import Path


def load_settings(overrides=None):
    overrides = overrides or {}
    base_dir = Path(__file__).resolve().parent.parent
    down_dir = (
        overrides.get("NETU_DOWN_DIR")
        or os.environ.get("NETU_DOWN_DIR")
        or str(base_dir / "down")
    )
    config_path = (
        overrides.get("NETU_CONFIG")
        or os.environ.get("NETU_CONFIG")
        or str(base_dir / ".passwords.yaml")
    )
    activity_log = (
        overrides.get("NETU_ACTIVITY_LOG")
        or os.environ.get("NETU_ACTIVITY_LOG")
        or str(Path(config_path).parent / "activity.jsonl")
    )
    activity_max = (
        overrides.get("NETU_ACTIVITY_MAX")
        or os.environ.get("NETU_ACTIVITY_MAX")
        or 2000
    )
    secret = (
        overrides.get("NETU_SECRET")
        or os.environ.get("NETU_SECRET")
        or "netu-dev-secret"
    )
    host = (
        overrides.get("NETU_HOST")
        or os.environ.get("NETU_HOST")
        or "0.0.0.0"
    )
    port = (
        overrides.get("NETU_PORT")
        or os.environ.get("NETU_PORT")
        or 8899
    )
    return {
        "DOWN_DIR": down_dir,
        "PASSWORD_CONFIG_PATH": config_path,
        "ACTIVITY_LOG_PATH": activity_log,
        "ACTIVITY_MAX_ENTRIES": int(activity_max),
        "SECRET_KEY": secret,
        "HOST": host,
        "PORT": int(port),
        "JSON_AS_ASCII": False,
        **overrides,
    }
