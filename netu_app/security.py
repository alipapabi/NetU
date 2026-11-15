import re
from pathlib import Path


_RESERVED_USERNAMES = {"root", "admin", "hidden", "trash"}
_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")
MAX_NOTE_LENGTH = 500


def normalize_note(value):
    """把任意输入规整为纯文字备注：剥离控制字符并限制长度。"""
    if not isinstance(value, str):
        return ""
    cleaned = "".join(
        char
        for char in value
        if char in "\n\t" or (ord(char) >= 32 and ord(char) != 127)
    )
    return cleaned.strip()[:MAX_NOTE_LENGTH]


def sanitize_filename(filename):
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", filename).strip(" .")
    return cleaned or "upload.bin"


def is_valid_username(username):
    if not isinstance(username, str):
        return False
    name = username.strip()
    if not _USERNAME_PATTERN.match(name):
        return False
    return name.lower() not in _RESERVED_USERNAMES


def resolve_under_root(root, filename):
    root_path = Path(root).resolve()
    target = (root_path / filename).resolve()
    if target != root_path and root_path not in target.parents:
        return None
    return target
