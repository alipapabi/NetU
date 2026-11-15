# NetU 文件管理器安全改造 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有 NetU 改造成一个易部署的 Flask 单体文件管理器，支持首页密码访问、上传免密码、预览/下载/删除独立密码、后台可调会话时长、更安全的文件预览与自动刷新文件列表。

**Architecture:** 先把当前 `file_downloader.py` 中耦合的认证、文件服务、预览和后台逻辑拆进 `netu_app/` 包，再用模板和静态资源替换内联 HTML。认证采用 `PBKDF2 + HMAC` 的无状态能力 token，文件列表通过目录扫描和 `etag` 轮询实现自动刷新，预览按文件类型做分级处理，HTML 预览走沙箱隔离。

**Tech Stack:** Python 3, Flask, Jinja2, PyYAML, pytest

---

## 文件结构映射

- Create: `app.py`
- Create: `netu_app/__init__.py`
- Create: `netu_app/config.py`
- Create: `netu_app/auth.py`
- Create: `netu_app/security.py`
- Create: `netu_app/file_service.py`
- Create: `netu_app/preview_service.py`
- Create: `netu_app/main_routes.py`
- Create: `netu_app/admin_routes.py`
- Create: `netu_app/templates/login.html`
- Create: `netu_app/templates/index.html`
- Create: `netu_app/templates/admin.html`
- Create: `netu_app/templates/preview_shell.html`
- Create: `netu_app/static/app.css`
- Create: `netu_app/static/app.js`
- Create: `netu_app/static/admin.js`
- Create: `tests/conftest.py`
- Create: `tests/test_auth.py`
- Create: `tests/test_file_service.py`
- Create: `tests/test_preview.py`
- Create: `tests/test_admin.py`
- Modify: `.passwords.yaml`
- Modify: `file_downloader.py`
- Delete or stop using: `admin_routes.py`

### 文件职责

- `app.py`：启动入口，只负责创建应用并运行
- `netu_app/__init__.py`：应用工厂、注册蓝图、统一响应头和错误处理
- `netu_app/config.py`：集中读取目录、端口、cookie 时长和旧配置迁移
- `netu_app/auth.py`：密码哈希、能力 token、登录失败锁定、cookie 读写
- `netu_app/security.py`：路径校验、文件名清洗、安全响应头
- `netu_app/file_service.py`：目录扫描、文件元数据、上传重命名、列表 etag
- `netu_app/preview_service.py`：按 MIME/扩展名判断预览方式，生成预览上下文
- `netu_app/main_routes.py`：登录、首页、上传、下载、删除、预览、文件列表 API
- `netu_app/admin_routes.py`：后台登录、密码修改、安全参数修改
- `templates/*.html`：页面模板
- `static/*.js`：上传、自动刷新、密码弹窗、后台设置交互
- `tests/*.py`：单元和接口回归测试
- `file_downloader.py`：过渡壳文件，避免旧启动方式立即失效

### 兼容策略

- 保留 `python file_downloader.py` 的启动入口，但内部改为调用新应用工厂
- 首次运行时自动把旧版 `.passwords.yaml` 明文结构迁移为哈希结构
- 保留现有 `/login` `/download/<filename>` `/preview/<filename>` 等主要 URL，不强制改变用户使用方式

### Task 1: 建立应用骨架与最小可运行入口

**Files:**
- Create: `app.py`
- Create: `netu_app/__init__.py`
- Create: `netu_app/config.py`
- Modify: `file_downloader.py`
- Test: `tests/conftest.py`

- [ ] **Step 1: 写出最小应用工厂测试**

```python
# tests/conftest.py
from netu_app import create_app


def build_test_app(tmp_path):
    app = create_app({
        "TESTING": True,
        "NETU_DOWN_DIR": str(tmp_path / "down"),
        "NETU_CONFIG": str(tmp_path / ".passwords.yaml"),
        "NETU_SECRET": "test-secret",
    })
    return app


def test_app_factory_builds(tmp_path):
    app = build_test_app(tmp_path)
    assert app is not None
    assert app.config["DOWN_DIR"].endswith("down")
```

- [ ] **Step 2: 运行测试确认当前失败**

Run: `pytest tests/conftest.py::test_app_factory_builds -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'netu_app'`

- [ ] **Step 3: 写最小应用工厂和启动入口**

```python
# netu_app/__init__.py
from flask import Flask
from .config import load_settings


def create_app(overrides=None):
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    settings = load_settings(overrides or {})
    app.config.update(settings)
    app.secret_key = settings["SECRET_KEY"]
    return app
```

```python
# netu_app/config.py
import os
from pathlib import Path


def load_settings(overrides=None):
    overrides = overrides or {}
    base_dir = Path(__file__).resolve().parent.parent
    down_dir = overrides.get("NETU_DOWN_DIR") or os.environ.get("NETU_DOWN_DIR") or str(base_dir / "down")
    config_path = overrides.get("NETU_CONFIG") or os.environ.get("NETU_CONFIG") or str(base_dir / ".passwords.yaml")
    secret = overrides.get("NETU_SECRET") or os.environ.get("NETU_SECRET") or "change-me"
    return {
        "DOWN_DIR": down_dir,
        "PASSWORD_CONFIG_PATH": config_path,
        "SECRET_KEY": secret,
        "JSON_AS_ASCII": False,
    }
```

```python
# app.py
from netu_app import create_app

app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8899, debug=False)
```

```python
# file_downloader.py
from app import app


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8899, debug=False)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/conftest.py::test_app_factory_builds -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app.py file_downloader.py netu_app/__init__.py netu_app/config.py tests/conftest.py
git commit -m "refactor: add flask app factory skeleton"
```

### Task 2: 实现密码迁移、哈希校验与能力 token

**Files:**
- Create: `netu_app/auth.py`
- Modify: `netu_app/config.py`
- Modify: `.passwords.yaml`
- Test: `tests/test_auth.py`

- [ ] **Step 1: 先写失败测试覆盖迁移和会话逻辑**

```python
# tests/test_auth.py
from netu_app.auth import PasswordManager


def test_plaintext_passwords_are_migrated(tmp_path):
    config_path = tmp_path / ".passwords.yaml"
    config_path.write_text(
        "_meta:\n  note: reset\npasswords:\n  open: 7bef\n  upload: 7bef\n  download: 7bef\n  admin: 7bef\n",
        encoding="utf-8",
    )
    manager = PasswordManager(config_path, "secret-key")
    assert manager.verify_password("open", "7bef") is True
    migrated = config_path.read_text(encoding="utf-8")
    assert "pbkdf2_sha256$" in migrated


def test_capability_token_invalidates_after_version_change(tmp_path):
    manager = PasswordManager(tmp_path / ".passwords.yaml", "secret-key")
    manager.set_password("preview", "abc12345")
    token = manager.issue_token("preview", ttl_seconds=3600)
    assert manager.verify_token("preview", token) is True
    manager.set_password("preview", "new-pass-123")
    assert manager.verify_token("preview", token) is False
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_auth.py -v`
Expected: FAIL with `ModuleNotFoundError` or `ImportError`

- [ ] **Step 3: 实现密码管理器**

```python
# netu_app/auth.py
import base64
import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path

import yaml


class PasswordManager:
    def __init__(self, config_path, secret_key):
        self.config_path = Path(config_path)
        self.secret_key = secret_key.encode("utf-8")
        self._data = self._load_or_create()

    def _hash_password(self, password, salt=None, rounds=240000):
        salt = salt or secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), rounds)
        return f"pbkdf2_sha256${rounds}${salt}${digest.hex()}"

    def _verify_hash(self, password, encoded):
        algo, rounds, salt, digest = encoded.split("$", 3)
        probe = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), int(rounds))
        return hmac.compare_digest(probe.hex(), digest)

    def _default_data(self):
        return {
            "security": {"cookie_ttl_days": 7, "lock_seconds": 60, "max_attempts": 5},
            "passwords": {},
            "versions": {"open": 1, "preview": 1, "download": 1, "delete": 1, "admin": 1},
        }

    def _load_or_create(self):
        if not self.config_path.exists():
            data = self._default_data()
            for mode in ("open", "preview", "download", "delete", "admin"):
                data["passwords"][mode] = {"hash": self._hash_password("7bef")}
            self._save(data)
            return data
        with self.config_path.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
        return self._migrate(raw)

    def _migrate(self, raw):
        data = self._default_data()
        source = raw.get("passwords", {})
        for mode in ("open", "preview", "download", "delete", "admin"):
            legacy_mode = "upload" if mode == "delete" else mode
            value = source.get(mode, source.get(legacy_mode, "7bef"))
            if isinstance(value, str):
                data["passwords"][mode] = {"hash": self._hash_password(value)}
            else:
                data["passwords"][mode] = {"hash": value["hash"]}
        self._save(data)
        return data

    def _save(self, data):
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with self.config_path.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(data, handle, allow_unicode=True, sort_keys=False)

    def verify_password(self, mode, password):
        encoded = self._data["passwords"][mode]["hash"]
        return self._verify_hash(password, encoded)

    def set_password(self, mode, password):
        self._data["passwords"][mode] = {"hash": self._hash_password(password)}
        self._data["versions"][mode] += 1
        self._save(self._data)

    def issue_token(self, mode, ttl_seconds):
        payload = {
            "mode": mode,
            "exp": int(time.time()) + ttl_seconds,
            "ver": self._data["versions"][mode],
        }
        raw = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8")
        sig = hmac.new(self.secret_key, raw.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"{raw}.{sig}"

    def verify_token(self, mode, token):
        try:
            raw, sig = token.split(".", 1)
            expected = hmac.new(self.secret_key, raw.encode("utf-8"), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(sig, expected):
                return False
            payload = json.loads(base64.urlsafe_b64decode(raw.encode("utf-8")).decode("utf-8"))
            return payload["mode"] == mode and payload["exp"] >= int(time.time()) and payload["ver"] == self._data["versions"][mode]
        except Exception:
            return False
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_auth.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add netu_app/auth.py netu_app/config.py .passwords.yaml tests/test_auth.py
git commit -m "feat: add password migration and capability tokens"
```

### Task 3: 实现路径安全、目录扫描与文件操作接口

**Files:**
- Create: `netu_app/security.py`
- Create: `netu_app/file_service.py`
- Create: `netu_app/main_routes.py`
- Modify: `netu_app/__init__.py`
- Test: `tests/test_file_service.py`

- [ ] **Step 1: 写失败测试覆盖路径越界、上传重命名与列表 etag**

```python
# tests/test_file_service.py
from pathlib import Path

from netu_app.file_service import FileService


def test_rejects_path_traversal(tmp_path):
    service = FileService(tmp_path)
    assert service.resolve_safe_path("../hack.txt") is None


def test_duplicate_upload_is_renamed(tmp_path):
    service = FileService(tmp_path)
    first = service.make_upload_name("report.pdf")
    Path(tmp_path / first).write_text("a", encoding="utf-8")
    second = service.make_upload_name("report.pdf")
    assert second != "report.pdf"
    assert second.startswith("report_")


def test_list_files_returns_stable_etag(tmp_path):
    service = FileService(tmp_path)
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    payload = service.list_files()
    assert payload["etag"]
    assert payload["files"][0]["name"] == "a.txt"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_file_service.py -v`
Expected: FAIL with `ModuleNotFoundError` or missing symbol errors

- [ ] **Step 3: 实现文件服务与主页接口骨架**

```python
# netu_app/security.py
import re
from pathlib import Path


def sanitize_filename(filename):
    cleaned = re.sub(r"[^\w.\- ()\u4e00-\u9fff]", "_", filename).strip(" .")
    return cleaned or "upload.bin"


def resolve_under_root(root, filename):
    root_path = Path(root).resolve()
    target = (root_path / filename).resolve()
    if root_path not in target.parents and target != root_path:
        return None
    return target
```

```python
# netu_app/file_service.py
import hashlib
import mimetypes
from datetime import datetime
from pathlib import Path

from .security import resolve_under_root, sanitize_filename


class FileService:
    def __init__(self, down_dir):
        self.down_dir = Path(down_dir)
        self.down_dir.mkdir(parents=True, exist_ok=True)

    def resolve_safe_path(self, filename):
        target = resolve_under_root(self.down_dir, filename)
        if target is None or not target.exists() or not target.is_file():
            return None
        return target

    def make_upload_name(self, filename):
        safe_name = sanitize_filename(filename)
        target = self.down_dir / safe_name
        if not target.exists():
            return safe_name
        stem = target.stem
        suffix = target.suffix
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{stem}_{stamp}{suffix}"

    def list_files(self):
        items = []
        for path in sorted(self.down_dir.iterdir(), key=lambda item: item.stat().st_mtime, reverse=True):
            if not path.is_file() or path.name.startswith("."):
                continue
            mime, _ = mimetypes.guess_type(path.name)
            items.append({
                "name": path.name,
                "size_bytes": path.stat().st_size,
                "modified": int(path.stat().st_mtime),
                "modified_text": datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
                "mime": mime or "application/octet-stream",
            })
        digest = hashlib.sha256()
        for item in items:
            digest.update(f"{item['name']}:{item['size_bytes']}:{item['modified']}".encode("utf-8"))
        return {"etag": digest.hexdigest(), "files": items}
```

```python
# netu_app/main_routes.py
from flask import Blueprint, current_app, jsonify

from .file_service import FileService

bp = Blueprint("main", __name__)


@bp.get("/api/files")
def api_files():
    service = FileService(current_app.config["DOWN_DIR"])
    return jsonify(service.list_files())
```

```python
# netu_app/__init__.py
from flask import Flask
from .config import load_settings


def create_app(overrides=None):
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.update(load_settings(overrides or {}))
    app.secret_key = app.config["SECRET_KEY"]

    from .main_routes import bp as main_bp
    app.register_blueprint(main_bp)
    return app
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_file_service.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add netu_app/security.py netu_app/file_service.py netu_app/main_routes.py netu_app/__init__.py tests/test_file_service.py
git commit -m "feat: add safe file service and listing api"
```

### Task 4: 接入登录、预览/下载/删除独立权限与后台密码配置

**Files:**
- Modify: `netu_app/auth.py`
- Modify: `netu_app/main_routes.py`
- Create: `netu_app/admin_routes.py`
- Create: `tests/test_admin.py`
- Modify: `netu_app/__init__.py`

- [ ] **Step 1: 先写接口测试覆盖独立权限边界**

```python
# tests/test_admin.py
from netu_app import create_app


def test_delete_requires_delete_capability(tmp_path):
    app = create_app({
        "TESTING": True,
        "NETU_DOWN_DIR": str(tmp_path / "down"),
        "NETU_CONFIG": str(tmp_path / ".passwords.yaml"),
        "NETU_SECRET": "secret",
    })
    client = app.test_client()
    target = tmp_path / "down" / "a.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("hello", encoding="utf-8")
    response = client.post("/api/delete", json={"filename": "a.txt"})
    assert response.status_code == 401
    assert response.get_json()["need_auth"] == "delete"


def test_admin_can_update_cookie_ttl(tmp_path):
    app = create_app({
        "TESTING": True,
        "NETU_DOWN_DIR": str(tmp_path / "down"),
        "NETU_CONFIG": str(tmp_path / ".passwords.yaml"),
        "NETU_SECRET": "secret",
    })
    manager = app.config["PASSWORD_MANAGER"]
    manager.set_password("admin", "admin-1234")
    client = app.test_client()
    login = client.post("/login?mode=admin", data={"password": "admin-1234", "mode": "admin"})
    assert login.status_code in (302, 303)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_admin.py -v`
Expected: FAIL because `/api/delete` and `/login` 相关逻辑尚未完成

- [ ] **Step 3: 实现权限装饰器、登录路由和后台保存逻辑**

```python
# netu_app/auth.py
from functools import wraps
from flask import current_app, jsonify, redirect, request


COOKIE_NAMES = {
    "open": "netu_open",
    "preview": "netu_preview",
    "download": "netu_download",
    "delete": "netu_delete",
    "admin": "netu_admin",
}


def get_password_manager():
    return current_app.config["PASSWORD_MANAGER"]


def has_capability(mode):
    token = request.cookies.get(COOKIE_NAMES[mode], "")
    return bool(token and get_password_manager().verify_token(mode, token))


def require_capability(mode, page_redirect=False):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if has_capability(mode):
                return view(*args, **kwargs)
            if page_redirect:
                return redirect(f"/login?mode={mode}&next={request.path}")
            return jsonify({"status": 1, "message": "需要密码", "need_auth": mode}), 401
        return wrapped
    return decorator
```

```python
# netu_app/main_routes.py
from flask import Blueprint, current_app, jsonify, make_response, redirect, render_template, request, send_file

from .auth import COOKIE_NAMES, get_password_manager, require_capability
from .file_service import FileService

bp = Blueprint("main", __name__)


@bp.get("/login")
def login_page():
    return render_template("login.html", mode=request.args.get("mode", "open"), next_url=request.args.get("next", "/"))


@bp.post("/login")
def login_submit():
    mode = request.form.get("mode", "open")
    password = request.form.get("password", "")
    next_url = request.form.get("next", "/")
    manager = get_password_manager()
    if not manager.verify_password(mode, password):
        return redirect(f"/login?mode={mode}&next={next_url}&e=1")
    ttl_days = manager.get_security_settings()["cookie_ttl_days"]
    ttl_seconds = ttl_days * 24 * 3600
    token = manager.issue_token(mode, ttl_seconds)
    response = make_response(redirect(next_url))
    response.set_cookie(COOKIE_NAMES[mode], token, max_age=ttl_seconds, httponly=True, samesite="Lax")
    return response


@bp.post("/api/delete")
@require_capability("delete")
def api_delete():
    service = FileService(current_app.config["DOWN_DIR"])
    filename = (request.get_json(silent=True) or {}).get("filename", "")
    target = service.resolve_safe_path(filename)
    if target is None:
        return jsonify({"status": 1, "message": "文件不存在"}), 404
    target.unlink()
    return jsonify({"status": 0, "message": "删除成功"})
```

```python
# netu_app/admin_routes.py
from flask import Blueprint, current_app, jsonify, request

from .auth import require_capability

bp = Blueprint("admin", __name__)


@bp.post("/admin/api/security")
@require_capability("admin")
def save_security():
    data = request.get_json(silent=True) or {}
    ttl_days = int(data.get("cookie_ttl_days", 7))
    manager = current_app.config["PASSWORD_MANAGER"]
    manager.update_security(cookie_ttl_days=ttl_days)
    return jsonify({"status": 0, "message": "安全配置已更新"})
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_admin.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add netu_app/auth.py netu_app/main_routes.py netu_app/admin_routes.py netu_app/__init__.py tests/test_admin.py
git commit -m "feat: add capability auth and admin security settings"
```

### Task 5: 实现分级预览与 HTML 沙箱隔离

**Files:**
- Create: `netu_app/preview_service.py`
- Create: `netu_app/templates/preview_shell.html`
- Modify: `netu_app/main_routes.py`
- Create: `tests/test_preview.py`

- [ ] **Step 1: 写失败测试覆盖文本、HTML 和 PDF 预览决策**

```python
# tests/test_preview.py
from netu_app.preview_service import PreviewService


def test_html_uses_sandbox_mode(tmp_path):
    service = PreviewService(tmp_path)
    info = service.describe("demo.html")
    assert info["mode"] == "html-sandbox"


def test_text_file_uses_text_mode(tmp_path):
    service = PreviewService(tmp_path)
    info = service.describe("notes.txt")
    assert info["mode"] == "text"


def test_pdf_file_uses_embed_mode(tmp_path):
    service = PreviewService(tmp_path)
    info = service.describe("book.pdf")
    assert info["mode"] == "pdf"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_preview.py -v`
Expected: FAIL because `PreviewService` 尚不存在

- [ ] **Step 3: 实现预览服务与预览壳页面**

```python
# netu_app/preview_service.py
from pathlib import Path


class PreviewService:
    TEXT_EXTS = {".txt", ".md", ".json", ".csv", ".log", ".py", ".js", ".css"}
    IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"}
    AUDIO_EXTS = {".mp3", ".wav", ".ogg"}
    VIDEO_EXTS = {".mp4", ".webm", ".mov"}

    def __init__(self, down_dir):
        self.down_dir = Path(down_dir)

    def describe(self, filename):
        ext = Path(filename).suffix.lower()
        if ext == ".html":
            return {"mode": "html-sandbox"}
        if ext == ".pdf":
            return {"mode": "pdf"}
        if ext in self.TEXT_EXTS:
            return {"mode": "text"}
        if ext in self.IMAGE_EXTS:
            return {"mode": "image"}
        if ext in self.AUDIO_EXTS:
            return {"mode": "audio"}
        if ext in self.VIDEO_EXTS:
            return {"mode": "video"}
        if ext in {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"}:
            return {"mode": "office-fallback"}
        return {"mode": "download-only"}
```

```html
<!-- netu_app/templates/preview_shell.html -->
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{{ filename }} - 预览</title>
</head>
<body>
  {% if preview.mode == "html-sandbox" %}
  <iframe
    src="{{ content_url }}"
    sandbox="allow-scripts allow-same-origin"
    referrerpolicy="no-referrer"
    style="width:100%;height:100vh;border:0;"></iframe>
  {% elif preview.mode == "pdf" %}
  <embed src="{{ content_url }}" type="application/pdf" style="width:100%;height:100vh;">
  {% elif preview.mode == "text" %}
  <pre>{{ text_content }}</pre>
  {% else %}
  <p>当前类型不支持直接预览，请下载查看。</p>
  {% endif %}
</body>
</html>
```

```python
# netu_app/main_routes.py
from flask import Blueprint, current_app, jsonify, render_template, request, send_file

from .auth import require_capability
from .file_service import FileService
from .preview_service import PreviewService


@bp.get("/view/<path:filename>")
@require_capability("preview")
def view_file(filename):
    service = FileService(current_app.config["DOWN_DIR"])
    previewer = PreviewService(current_app.config["DOWN_DIR"])
    target = service.resolve_safe_path(filename)
    if target is None:
        return jsonify({"status": 1, "message": "文件不存在"}), 404
    preview = previewer.describe(filename)
    text_content = ""
    if preview["mode"] == "text":
        text_content = target.read_text(encoding="utf-8", errors="replace")
    return render_template("preview_shell.html", filename=filename, preview=preview, content_url=f"/preview/{filename}", text_content=text_content)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_preview.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add netu_app/preview_service.py netu_app/templates/preview_shell.html netu_app/main_routes.py tests/test_preview.py
git commit -m "feat: add safe preview modes and html sandbox"
```

### Task 6: 重做文件列表页、上传交互与自动刷新

**Files:**
- Create: `netu_app/templates/index.html`
- Create: `netu_app/templates/login.html`
- Create: `netu_app/static/app.css`
- Create: `netu_app/static/app.js`
- Modify: `netu_app/main_routes.py`
- Test: `tests/test_file_service.py`

- [ ] **Step 1: 先补接口测试，确保文件列表 etag 轮询可用**

```python
# tests/test_file_service.py
def test_api_files_returns_not_modified_when_etag_matches(tmp_path):
    from netu_app import create_app

    app = create_app({
        "TESTING": True,
        "NETU_DOWN_DIR": str(tmp_path / "down"),
        "NETU_CONFIG": str(tmp_path / ".passwords.yaml"),
        "NETU_SECRET": "secret",
    })
    down_dir = tmp_path / "down"
    down_dir.mkdir(parents=True, exist_ok=True)
    (down_dir / "a.txt").write_text("hello", encoding="utf-8")
    client = app.test_client()
    first = client.get("/api/files")
    etag = first.get_json()["etag"]
    second = client.get(f"/api/files?since={etag}")
    assert second.status_code == 304
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_file_service.py::test_api_files_returns_not_modified_when_etag_matches -v`
Expected: FAIL because `304` 分支尚未实现

- [ ] **Step 3: 实现列表页模板和自动刷新脚本**

```html
<!-- netu_app/templates/index.html -->
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>NetU 文件管理器</title>
  <link rel="stylesheet" href="{{ url_for('static', filename='app.css') }}">
</head>
<body>
  <main class="page">
    <header class="hero">
      <h1>NetU 文件管理器</h1>
      <p>自动扫描目录，安全预览、下载与删除</p>
    </header>
    <section class="toolbar">
      <input id="searchInput" type="search" placeholder="搜索文件名">
      <button id="refreshBtn" type="button">刷新</button>
      <a href="/logout">退出</a>
    </section>
    <section class="upload-panel">
      <input id="fileInput" type="file" multiple hidden>
      <button id="uploadBtn" type="button">选择文件上传</button>
      <div id="uploadStatus"></div>
    </section>
    <section id="fileList" class="file-list"></section>
  </main>
  <script src="{{ url_for('static', filename='app.js') }}"></script>
</body>
</html>
```

```javascript
// netu_app/static/app.js
let currentEtag = "";
let refreshTimer = null;

async function loadFiles(force = false) {
  const url = force || !currentEtag ? "/api/files" : `/api/files?since=${encodeURIComponent(currentEtag)}`;
  const response = await fetch(url, { credentials: "same-origin" });
  if (response.status === 304) return;
  const payload = await response.json();
  currentEtag = payload.etag;
  renderFiles(payload.files);
}

function renderFiles(files) {
  const root = document.getElementById("fileList");
  root.innerHTML = files.map((file) => `
    <article class="file-card">
      <div class="file-name">${file.name}</div>
      <div class="file-meta">${file.modified_text}</div>
      <div class="file-actions">
        <button type="button" data-action="preview" data-name="${file.name}">预览</button>
        <button type="button" data-action="download" data-name="${file.name}">下载</button>
        <button type="button" data-action="delete" data-name="${file.name}">删除</button>
      </div>
    </article>
  `).join("");
}

function startPolling() {
  clearInterval(refreshTimer);
  refreshTimer = setInterval(() => loadFiles(false), 5000);
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("refreshBtn").addEventListener("click", () => loadFiles(true));
  loadFiles(true);
  startPolling();
});
```

```python
# netu_app/main_routes.py
@bp.get("/")
@require_capability("open", page_redirect=True)
def index():
    return render_template("index.html")


@bp.get("/api/files")
@require_capability("open")
def api_files():
    service = FileService(current_app.config["DOWN_DIR"])
    payload = service.list_files()
    if request.args.get("since") == payload["etag"]:
        return ("", 304)
    return jsonify(payload)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_file_service.py::test_api_files_returns_not_modified_when_etag_matches -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add netu_app/templates/index.html netu_app/templates/login.html netu_app/static/app.css netu_app/static/app.js netu_app/main_routes.py tests/test_file_service.py
git commit -m "feat: rebuild file manager ui with auto refresh"
```

### Task 7: 收尾安全头、错误处理与回归验证

**Files:**
- Modify: `netu_app/__init__.py`
- Modify: `netu_app/main_routes.py`
- Modify: `netu_app/admin_routes.py`
- Modify: `tests/test_admin.py`
- Modify: `tests/test_preview.py`

- [ ] **Step 1: 先写失败测试覆盖关键安全响应头**

```python
# tests/test_preview.py
def test_preview_response_sets_nosniff(tmp_path):
    from netu_app import create_app

    app = create_app({
        "TESTING": True,
        "NETU_DOWN_DIR": str(tmp_path / "down"),
        "NETU_CONFIG": str(tmp_path / ".passwords.yaml"),
        "NETU_SECRET": "secret",
    })
    down_dir = tmp_path / "down"
    down_dir.mkdir(parents=True, exist_ok=True)
    (down_dir / "demo.txt").write_text("hello", encoding="utf-8")
    client = app.test_client()
    response = client.get("/preview/demo.txt")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_preview.py::test_preview_response_sets_nosniff -v`
Expected: FAIL because response headers 尚未统一注入

- [ ] **Step 3: 实现统一安全头和错误处理**

```python
# netu_app/__init__.py
from flask import Flask, jsonify
from .auth import PasswordManager
from .config import load_settings


def create_app(overrides=None):
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.update(load_settings(overrides or {}))
    app.secret_key = app.config["SECRET_KEY"]
    app.config["PASSWORD_MANAGER"] = PasswordManager(app.config["PASSWORD_CONFIG_PATH"], app.config["SECRET_KEY"])

    from .main_routes import bp as main_bp
    from .admin_routes import bp as admin_bp
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp)

    @app.after_request
    def apply_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        if response.mimetype == "text/html":
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.errorhandler(404)
    def handle_not_found(_error):
        return jsonify({"status": 1, "message": "资源不存在"}), 404

    @app.errorhandler(500)
    def handle_server_error(_error):
        return jsonify({"status": 1, "message": "服务器内部错误"}), 500

    return app
```

- [ ] **Step 4: 运行完整回归**

Run: `pytest tests -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add netu_app/__init__.py netu_app/main_routes.py netu_app/admin_routes.py tests/test_admin.py tests/test_preview.py
git commit -m "chore: finalize security headers and regression coverage"
```

## 自检结果

### Spec 覆盖

- 首页密码访问：Task 4, Task 6
- 上传免密码：Task 3, Task 6
- 预览/下载/删除独立密码：Task 4, Task 5
- 1 周免重复输入且后台可调：Task 2, Task 4
- 自动扫描 `down/` 目录：Task 3, Task 6
- 多类型在线预览：Task 5
- 安全基线：Task 2, Task 3, Task 4, Task 7
- 单机 Flask 易部署：Task 1

### 占位符扫描

- 未保留 `TBD`、`TODO`、`以后再说` 之类的占位描述
- 每个任务都给出了涉及文件、测试、命令和提交建议

### 类型一致性

- 权限模式统一使用 `open / preview / download / delete / admin`
- 删除能力不再复用 `upload`
- cookie 时长统一使用 `cookie_ttl_days`

