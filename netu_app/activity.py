import json
import threading
from datetime import datetime
from pathlib import Path

from flask import current_app, request


TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
SUPERADMIN_USERNAME = "superadmin"
DEFAULT_MAX_ENTRIES = 2000

ACTION_LABELS = {
    "login": "登录",
    "upload": "上传",
    "download": "下载",
    "delete": "删除",
}
VALID_ACTIONS = tuple(ACTION_LABELS)


class ActivityLog:
    """用户行为记录（登录/上传/下载/删除），持久化为追加写入的 JSONL 文件。

    每行是一条 JSON 记录::

        {"at": "2026-11-16 14:30:05", "username": "alice",
         "action": "upload", "filename": "a.txt", "ip": "192.168.1.5"}

    记录按时间顺序追加，保留最近的 ``max_entries`` 条，超出后自动丢弃最旧的。
    为避免每条记录都重写整份文件，实际容忍写入到 ``max_entries + trim_margin``
    条时才压缩一次。
    """

    def __init__(self, path, max_entries=DEFAULT_MAX_ENTRIES):
        self.path = Path(path)
        try:
            self.max_entries = max(1, int(max_entries))
        except (TypeError, ValueError):
            self.max_entries = DEFAULT_MAX_ENTRIES
        self.trim_margin = max(1, self.max_entries // 4)
        self._lock = threading.Lock()
        self._count = self._count_lines()

    def _count_lines(self):
        if not self.path.exists():
            return 0
        count = 0
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if line.strip():
                        count += 1
        except OSError:
            return 0
        return count

    def _read_all(self):
        if not self.path.exists():
            return []
        records = []
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        records.append(json.loads(line))
                    except (TypeError, ValueError):
                        continue
        except OSError:
            return []
        return records

    def _write_all(self, records):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._count = len(records)

    def record(self, username, action, filename="", ip=""):
        """追加一条行为记录。非法 action 直接忽略，不影响主流程。"""
        if action not in VALID_ACTIONS:
            return None
        entry = {
            "at": datetime.now().strftime(TIME_FORMAT),
            "username": username or SUPERADMIN_USERNAME,
            "action": action,
            "filename": str(filename or ""),
            "ip": str(ip or ""),
        }
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
            self._count += 1
            if self._count > self.max_entries + self.trim_margin:
                self._write_all(self._read_all()[-self.max_entries :])
        return entry

    def list_records(self, username=None, limit=None):
        """返回记录，最新的在前；``username`` 为空表示不过滤（全部记录）。"""
        with self._lock:
            records = self._read_all()
        if username:
            records = [item for item in records if item.get("username") == username]
        records.reverse()
        if limit is not None:
            records = records[: max(0, int(limit))]
        return records

    def clear(self, username=None):
        """删除记录；``username`` 为空表示清空全部，否则只清空该用户名。"""
        with self._lock:
            records = self._read_all()
            if not username:
                self._write_all([])
                return len(records)
            kept = [item for item in records if item.get("username") != username]
            removed = len(records) - len(kept)
            if removed:
                self._write_all(kept)
        return removed


# ---------------- Flask 集成 ----------------
def get_activity_log():
    return current_app.config["ACTIVITY_LOG"]


def log_activity(username, action, filename=""):
    """记录一条行为；来源 IP 只取直连地址（不信任可伪造的转发头）。"""
    get_activity_log().record(username, action, filename, request.remote_addr or "")
