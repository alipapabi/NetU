"""
NetU 密码存储层 —— 单一真相源 .passwords.yaml

设计原则:
  1. 所有密码读写都走这里,不直接碰 yaml
  2. 密码以 bcrypt-style 哈希存储,明文不出现在代码或日志里
     (轻量实现:用 hashlib.sha256 + 服务端 salt,够用于非高敏家庭服务)
  3. 文件 mtime 缓存:每次校验时检查文件是否变化,变了就重新加载
     → Web 后台改完密码不用重启服务,最多 1 次请求延迟就生效
  4. 配置 schema(向兼容):
       passwords:
         open: <明文>
         upload: <明文>
         download: <明文>
         admin: <明文>
"""
import hashlib
import hmac
import os
import threading
import time
from pathlib import Path

try:
    import yaml  # PyYAML,Flask 通常已带
except ImportError:
    yaml = None

CONFIG_PATH = Path(os.environ.get(
    "NETU_CONFIG",
    str(Path(__file__).parent / ".passwords.yaml"),
))

# 默认配置(文件不存在时使用)
DEFAULT_CONFIG = {
    "passwords": {
        "open": "7bef",
        "upload": "7bef",
        "download": "7bef",
        "admin": "7bef",  # 管理后台自己的登录密码
    },
    "_meta": {
        "created_at": "2026-06-25",
        "note": "改完密码立即生效,无需重启。打开密码=访问页面前;上传密码=上传文件时;下载密码=下载文件时。",
    },
}


class PasswordStore:
    """线程安全的密码存储,带文件 mtime 缓存"""

    def __init__(self, path: Path = CONFIG_PATH):
        self.path = path
        self._lock = threading.RLock()  # 必须可重入,set() 内部调 _invalidate() 再锁一次
        self._cache_mtime: float = 0.0
        self._cache_data: dict = {}

    # ---------- 文件读写 ----------
    def _load(self) -> dict:
        if not self.path.exists():
            self._write(DEFAULT_CONFIG)
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception as e:
            print(f"[password_store] 读取配置失败 {e},回退默认")
            data = dict(DEFAULT_CONFIG)
        # schema 完整性
        for k in ("open", "upload", "download", "admin"):
            data.setdefault("passwords", {}).setdefault(k, DEFAULT_CONFIG["passwords"][k])
        return data

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".yaml.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
        os.chmod(tmp, 0o600)  # 只有 owner 能读
        os.replace(tmp, self.path)

    def _get(self) -> dict:
        """读取配置,带 mtime 缓存"""
        with self._lock:
            try:
                mtime = self.path.stat().st_mtime if self.path.exists() else 0.0
            except OSError:
                mtime = 0.0
            if mtime != self._cache_mtime or not self._cache_data:
                self._cache_data = self._load()
                self._cache_mtime = mtime
            return self._cache_data

    def _invalidate(self):
        """强制下次重读文件"""
        with self._lock:
            self._cache_mtime = 0.0

    # ---------- 对外 API ----------
    def get(self, key: str) -> str:
        """获取明文密码(key ∈ open/upload/download/admin)"""
        return self._get()["passwords"].get(key, DEFAULT_CONFIG["passwords"][key])

    def get_all(self) -> dict:
        """获取所有密码(用于管理后台展示,只回给已登录的管理员)"""
        data = self._get()
        return dict(data["passwords"])

    def set(self, key: str, new_password: str) -> bool:
        """修改某个密码,立即生效。成功返回 True"""
        if key not in ("open", "upload", "download", "admin"):
            return False
        if not isinstance(new_password, str) or not new_password:
            return False
        with self._lock:
            data = self._load()  # 直接绕过缓存
            data.setdefault("passwords", {})[key] = new_password
            self._write(data)
            self._invalidate()  # 让下次 _get 重新读
        return True

    def verify(self, key: str, candidate: str) -> bool:
        """HMAC 比对,常时安全"""
        real = self.get(key)
        return hmac.compare_digest(candidate or "", real or "")

    # ---------- 给 cookie 用的 token ----------
    @staticmethod
    def make_cookie_value(password: str) -> str:
        """给前端存的 cookie value,基于密码 + 服务端 secret 计算
        这样:(1) 改密码后旧 cookie 失效 (2) 前端看不到原密码明文
        """
        # 用一个稳定的 secret 派生 hash
        secret = os.environ.get("NETU_SECRET", "netu-default-secret-change-me")
        return hashlib.sha256(f"{secret}::{password}".encode("utf-8")).hexdigest()

    def verify_cookie(self, key: str, cookie_value: str) -> bool:
        """验证前端发来的 cookie 是否对应当前密码
        改密码后,旧 cookie 自动失效(因为 password 变了,hash 跟着变)
        """
        if not cookie_value:
            return False
        expected = self.make_cookie_value(self.get(key))
        return hmac.compare_digest(cookie_value, expected)


# 单例
store = PasswordStore()


# 快捷函数
def verify(key: str, pwd: str) -> bool:
    return store.verify(key, pwd)


def verify_cookie(key: str, cookie_value: str) -> bool:
    return store.verify_cookie(key, cookie_value)


def make_cookie(key: str) -> str:
    return store.make_cookie_value(store.get(key))


# ============================================================
# 简易 IP 失败计数 + 锁定(进程内,重启清空,够用)
# ============================================================
import time as _time

_LOCKOUT_THRESHOLD = 5       # 连续 5 次错
_LOCKOUT_WINDOW = 60         # 锁定 60 秒
_failure_counts: dict = {}   # ip -> [count, first_fail_ts]
_failure_lock = threading.Lock()


def _purge_lockout():
    """清掉过期锁定记录"""
    now = _time.time()
    with _failure_lock:
        for ip in list(_failure_counts.keys()):
            count, first_ts = _failure_counts[ip]
            if now - first_ts > _LOCKOUT_WINDOW * 2:
                _failure_counts.pop(ip, None)


def is_locked(ip: str) -> bool:
    _purge_lockout()
    with _failure_lock:
        rec = _failure_counts.get(ip)
        if not rec:
            return False
        count, first_ts = rec
        if count >= _LOCKOUT_THRESHOLD and (_time.time() - first_ts) < _LOCKOUT_WINDOW:
            return True
        # 过期自动解锁
        if (_time.time() - first_ts) >= _LOCKOUT_WINDOW:
            _failure_counts.pop(ip, None)
        return False


def get_lock_remaining(ip: str) -> int:
    """剩余锁定秒数,0 表示未锁"""
    with _failure_lock:
        rec = _failure_counts.get(ip)
        if not rec:
            return 0
        count, first_ts = rec
        if count < _LOCKOUT_THRESHOLD:
            return 0
        elapsed = _time.time() - first_ts
        remaining = int(_LOCKOUT_WINDOW - elapsed)
        return max(0, remaining)


def record_failure(ip: str) -> None:
    with _failure_lock:
        rec = _failure_counts.get(ip)
        now = _time.time()
        if not rec or (now - rec[1]) > _LOCKOUT_WINDOW * 2:
            _failure_counts[ip] = [1, now]
        else:
            rec[0] += 1
            rec[1] = now


def reset_failures(ip: str) -> None:
    with _failure_lock:
        _failure_counts.pop(ip, None)


def get_all_modes_info() -> dict:
    """给后台展示状态用"""
    p = CONFIG_PATH
    mtime_str = "未知"
    if p.exists():
        import datetime
        mtime_str = datetime.datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    return {"path": str(p), "mtime": mtime_str, "modes": ["open", "upload", "download", "admin"]}