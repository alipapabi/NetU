import hashlib
import json
import mimetypes
from datetime import datetime
from pathlib import Path

from .security import normalize_note, resolve_under_root, sanitize_filename


class FileService:
    """管理某个目录（账户目录或公共区根目录）下的文件。

    软删除通过把文件移动到该目录下的 ``.hidden`` 子目录实现；
    只有超级管理员可以真正物理删除。

    文件备注存放在目录内的 ``.notes.json``（以文件名为键），
    该文件以 ``.`` 开头，不会出现在文件列表中。
    """

    HIDDEN_DIR_NAME = ".hidden"
    NOTES_FILE_NAME = ".notes.json"

    def __init__(self, base_dir):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.hidden_dir = self.base_dir / self.HIDDEN_DIR_NAME

    def _describe(self, path):
        stat = path.stat()
        mime, _ = mimetypes.guess_type(path.name)
        return {
            "name": path.name,
            "size_bytes": stat.st_size,
            "modified": int(stat.st_mtime),
            "modified_text": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
            "mime": mime or "application/octet-stream",
        }

    def _collect(self, directory):
        if not directory.is_dir():
            return []
        paths = [
            path
            for path in directory.iterdir()
            if path.is_file() and not path.name.startswith(".")
        ]
        paths.sort(key=lambda item: item.stat().st_mtime, reverse=True)
        return [self._describe(path) for path in paths]

    def list_files(self, include_hidden=True):
        notes = self.read_notes()
        files = self._collect(self.base_dir)
        hidden = self._collect(self.hidden_dir) if include_hidden else []
        for item in files + hidden:
            item["note"] = notes.get(item["name"], "")
        digest = hashlib.sha256()
        for item in files + hidden:
            digest.update(
                f"{item['name']}:{item['size_bytes']}:{item['modified']}".encode("utf-8")
            )
        return {"etag": digest.hexdigest(), "files": files, "hidden": hidden}

    # ---------------- 备注 ----------------
    def _notes_path(self):
        return self.base_dir / self.NOTES_FILE_NAME

    def read_notes(self):
        path = self._notes_path()
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {
            str(name): str(note)
            for name, note in data.items()
            if isinstance(name, str) and isinstance(note, str) and note
        }

    def write_note(self, filename, note):
        """为已存在的文件写入备注；返回 False 表示文件不存在。"""
        if self.resolve_any(filename) is None:
            return False
        notes = self.read_notes()
        cleaned = normalize_note(note)
        if cleaned:
            notes[filename] = cleaned
        else:
            notes.pop(filename, None)
        path = self._notes_path()
        if notes:
            path.write_text(
                json.dumps(notes, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        elif path.exists():
            path.unlink()
        return True

    def resolve_visible(self, filename):
        target = resolve_under_root(self.base_dir, filename)
        if target is None or not target.exists() or not target.is_file():
            return None
        return target

    def resolve_any(self, filename):
        target = self.resolve_visible(filename)
        if target is not None:
            return target
        hidden = resolve_under_root(self.hidden_dir, filename)
        if hidden is None or not hidden.exists() or not hidden.is_file():
            return None
        return hidden

    def make_upload_name(self, filename):
        safe_name = sanitize_filename(filename)
        target = self.base_dir / safe_name
        if not target.exists():
            return safe_name
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{target.stem}_{stamp}{target.suffix}"

    def _unique(self, directory, name):
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / name
        if not target.exists():
            return target
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return directory / f"{target.stem}_{stamp}{target.suffix}"

    def hide(self, filename):
        target = self.resolve_visible(filename)
        if target is None:
            return False
        destination = self._unique(self.hidden_dir, target.name)
        target.replace(destination)
        return True

    def restore(self, filename):
        target = resolve_under_root(self.hidden_dir, filename)
        if target is None or not target.exists() or not target.is_file():
            return False
        destination = self._unique(self.base_dir, target.name)
        target.replace(destination)
        return True

    def purge(self, filename):
        target = self.resolve_any(filename)
        if target is None:
            return False
        target.unlink()
        return True
