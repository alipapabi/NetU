import base64
import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import current_app, g, jsonify, redirect, request
import yaml

from .security import is_valid_username, normalize_note


SCHEMA_VERSION = 2
DEFAULT_PASSWORD = "7bef9fb4b0"
ACCOUNT_ABILITIES = ("download", "delete")

# 新账户默认有效期（天）：到期后自动停用；0 表示永不过期。
DEFAULT_ACCOUNT_EXPIRE_DAYS = 30
EXPIRE_FORMAT = "%Y-%m-%d %H:%M"

SESSION_COOKIE = "netu_session"
ADMIN_COOKIE = "netu_admin"
ABILITY_COOKIES = {
    "download": "netu_download",
    "delete": "netu_delete",
}
ALL_COOKIE_NAMES = [SESSION_COOKIE, ADMIN_COOKIE, *ABILITY_COOKIES.values()]


def parse_expire_days(value):
    """把输入规范为不小于 0 的整数天数；非法值回退为 0（永不过期）。"""
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def compute_expires_at(expire_days, base=None):
    """按天数计算到期时间字符串；0 天表示永不过期，返回空串。"""
    days = parse_expire_days(expire_days)
    if days <= 0:
        return ""
    return ((base or datetime.now()) + timedelta(days=days)).strftime(EXPIRE_FORMAT)


def expires_at_passed(expires_at):
    """判断到期时间是否已过；空串或无法解析均视为未过期。"""
    if not expires_at:
        return False
    try:
        deadline = datetime.strptime(expires_at, EXPIRE_FORMAT)
    except (TypeError, ValueError):
        return False
    return datetime.now() > deadline


class AccountManager:
    """账户与密码的单一真相源，持久化在 .passwords.yaml。

    结构:
      security:    {cookie_ttl_days, lock_seconds, max_attempts}
      superadmin:  {hash, version}
      accounts:    {<username>: {login_hash, download_hash, delete_hash,
                                 login_password, download_password, delete_password,
                                 note, version, enabled, created_at,
                                 expire_days, expires_at}}

    校验始终使用 *_hash（PBKDF2）；``*_password`` 是明文字段，仅为超级管理员
    「查看/复制/再分享」已设置的密码而保留，只有超级管理员接口会读取。
    """

    def __init__(self, config_path, secret_key):
        self.config_path = Path(config_path)
        self.secret_key = secret_key.encode("utf-8")
        self._data = self._load_or_create()

    # ---------------- 哈希 ----------------
    def _hash_password(self, password, salt=None, rounds=240000):
        salt = salt or secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            str(password).encode("utf-8"),
            salt.encode("utf-8"),
            rounds,
        )
        return f"pbkdf2_sha256${rounds}${salt}${digest.hex()}"

    def _verify_hash(self, password, encoded_hash):
        try:
            _algo, rounds, salt, digest = encoded_hash.split("$", 3)
            probe = hashlib.pbkdf2_hmac(
                "sha256",
                str(password).encode("utf-8"),
                salt.encode("utf-8"),
                int(rounds),
            )
            return hmac.compare_digest(probe.hex(), digest)
        except Exception:
            return False

    # ---------------- 读写 ----------------
    def _default_data(self):
        return {
            "schema_version": SCHEMA_VERSION,
            "security": {"cookie_ttl_days": 7, "lock_seconds": 60, "max_attempts": 5},
            "superadmin": {"hash": self._hash_password(DEFAULT_PASSWORD), "version": 1},
            "accounts": {},
        }

    def _save(self, data):
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with self.config_path.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(data, handle, allow_unicode=True, sort_keys=False)

    def _extract_hash(self, value):
        if isinstance(value, dict) and isinstance(value.get("hash"), str):
            return value["hash"]
        if isinstance(value, str) and value:
            return self._hash_password(value)
        return None

    def _load_or_create(self):
        if not self.config_path.exists():
            data = self._default_data()
            self._save(data)
            return data
        with self.config_path.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
        if not raw.get("accounts") and raw.get("passwords"):
            return self._migrate_legacy(raw)
        return self._normalize(raw)

    def _migrate_legacy(self, raw):
        """旧的单租户配置（全局 open/preview/download/delete/admin 密码）迁移。

        旧的 admin 密码保留为超级管理员密码，旧的文件仍留在 down 根目录（公共区）。
        """
        data = self._default_data()
        raw_security = raw.get("security", {})
        for key in data["security"]:
            if key in raw_security:
                data["security"][key] = raw_security[key]
        admin_hash = self._extract_hash((raw.get("passwords") or {}).get("admin"))
        if admin_hash:
            data["superadmin"]["hash"] = admin_hash
        data["accounts"] = {}
        self._save(data)
        return data

    def _normalize(self, raw):
        data = self._default_data()
        raw_security = raw.get("security") or {}
        for key in data["security"]:
            if key in raw_security:
                data["security"][key] = raw_security[key]

        superadmin = raw.get("superadmin") or {}
        if isinstance(superadmin.get("hash"), str):
            data["superadmin"]["hash"] = superadmin["hash"]
        try:
            data["superadmin"]["version"] = max(1, int(superadmin.get("version", 1)))
        except (TypeError, ValueError):
            data["superadmin"]["version"] = 1

        accounts = {}
        for username, cfg in (raw.get("accounts") or {}).items():
            if not is_valid_username(username) or not isinstance(cfg, dict):
                continue
            login_hash = cfg.get("login_hash")
            if not isinstance(login_hash, str):
                continue
            accounts[username] = {
                "login_hash": login_hash,
                "download_hash": cfg.get("download_hash") or login_hash,
                "delete_hash": cfg.get("delete_hash") or login_hash,
                "login_password": cfg.get("login_password") or "",
                "download_password": cfg.get("download_password") or "",
                "delete_password": cfg.get("delete_password") or "",
                "note": normalize_note(cfg.get("note") or ""),
                "version": max(1, int(cfg.get("version", 1))),
                "enabled": bool(cfg.get("enabled", True)),
                "created_at": cfg.get("created_at", ""),
                "expire_days": parse_expire_days(cfg.get("expire_days", 0)),
                "expires_at": cfg.get("expires_at") or "",
            }
        data["accounts"] = accounts
        return data

    # ---------------- 安全设置 ----------------
    def get_security_settings(self):
        return dict(self._data["security"])

    def update_security(self, **kwargs):
        for key, value in kwargs.items():
            if key in self._data["security"] and value is not None:
                self._data["security"][key] = value
        self._save(self._data)

    # ---------------- 超级管理员 ----------------
    def verify_superadmin_password(self, password):
        return self._verify_hash(password, self._data["superadmin"]["hash"])

    def set_superadmin_password(self, password):
        self._data["superadmin"]["hash"] = self._hash_password(password)
        self._data["superadmin"]["version"] += 1
        self._save(self._data)

    # ---------------- 账户 CRUD ----------------
    @staticmethod
    def _is_expired(account):
        """账户是否已过有效期（到期即视为停用）。"""
        return expires_at_passed(account.get("expires_at", ""))

    def list_accounts(self):
        result = []
        for username, cfg in self._data["accounts"].items():
            login_password = cfg.get("login_password", "")
            download_password = cfg.get("download_password", "")
            delete_password = cfg.get("delete_password", "")
            expired = self._is_expired(cfg)
            result.append(
                {
                    "username": username,
                    "enabled": bool(cfg.get("enabled", True)),
                    "created_at": cfg.get("created_at", ""),
                    "expire_days": parse_expire_days(cfg.get("expire_days", 0)),
                    "expires_at": cfg.get("expires_at", ""),
                    "expired": expired,
                    "login_password": login_password,
                    "download_password": download_password,
                    "delete_password": delete_password,
                    "note": cfg.get("note", ""),
                    "passwords_visible": bool(
                        login_password and download_password and delete_password
                    ),
                }
            )
        return result

    def get_account(self, username):
        return self._data["accounts"].get(username)

    def _validate_login_password(self, password, exclude=None):
        if not isinstance(password, str) or len(password) < 4:
            raise ValueError("登录密码至少 4 位")
        if self.verify_superadmin_password(password):
            raise ValueError("该密码与超级管理员密码相同，请更换")
        for username, cfg in self._data["accounts"].items():
            if username != exclude and self._verify_hash(password, cfg["login_hash"]):
                raise ValueError("该登录密码已被其他账户使用，请更换")

    def create_account(self, username, login_password, download_password, delete_password, enabled=True, expire_days=None):
        username = (username or "").strip()
        if not is_valid_username(username):
            raise ValueError("用户名不合法（字母或数字开头，仅限字母数字 _ - . ，最长 32 位）")
        if username in self._data["accounts"]:
            raise ValueError("用户名已存在")
        self._validate_login_password(login_password)
        for label, value in (("下载密码", download_password), ("删除密码", delete_password)):
            if not isinstance(value, str) or len(value) < 4:
                raise ValueError(f"{label}至少 4 位")
        days = DEFAULT_ACCOUNT_EXPIRE_DAYS if expire_days is None else parse_expire_days(expire_days)
        self._data["accounts"][username] = {
            "login_hash": self._hash_password(login_password),
            "download_hash": self._hash_password(download_password),
            "delete_hash": self._hash_password(delete_password),
            "login_password": login_password,
            "download_password": download_password,
            "delete_password": delete_password,
            "note": "",
            "version": 1,
            "enabled": bool(enabled),
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "expire_days": days,
            "expires_at": compute_expires_at(days),
        }
        self._save(self._data)
        return username

    def update_account(self, username, login_password=None, download_password=None, delete_password=None, enabled=None, expire_days=None):
        account = self._data["accounts"].get(username)
        if account is None:
            raise ValueError("账户不存在")
        changed = False
        if login_password is not None:
            if not login_password:
                raise ValueError("登录密码不能为空")
            self._validate_login_password(login_password, exclude=username)
            account["login_hash"] = self._hash_password(login_password)
            account["login_password"] = login_password
            changed = True
        if download_password is not None:
            if not download_password:
                raise ValueError("下载密码不能为空")
            if len(download_password) < 4:
                raise ValueError("下载密码至少 4 位")
            account["download_hash"] = self._hash_password(download_password)
            account["download_password"] = download_password
            changed = True
        if delete_password is not None:
            if not delete_password:
                raise ValueError("删除密码不能为空")
            if len(delete_password) < 4:
                raise ValueError("删除密码至少 4 位")
            account["delete_hash"] = self._hash_password(delete_password)
            account["delete_password"] = delete_password
            changed = True
        if expire_days is not None:
            # 只要提交了有效期就按提交值重算，到期时间从本次保存时刻起算。
            account["expire_days"] = parse_expire_days(expire_days)
            account["expires_at"] = compute_expires_at(account["expire_days"])
            changed = True
        if enabled is not None:
            account["enabled"] = bool(enabled)
            changed = True
        if changed:
            account["version"] = account.get("version", 1) + 1
            self._save(self._data)
        return changed

    def remove_account(self, username):
        if username in self._data["accounts"]:
            del self._data["accounts"][username]
            self._save(self._data)
            return True
        return False

    def set_account_note(self, username, note):
        """更新账户备注。备注不属于凭据，不递增 version，避免打断已登录会话。"""
        account = self._data["accounts"].get(username)
        if account is None:
            raise ValueError("账户不存在")
        account["note"] = normalize_note(note)
        self._save(self._data)
        return account["note"]

    # ---------------- 校验 ----------------
    def match_login(self, password):
        """按密码识别登录身份，返回 {role, username} 或 None。"""
        if not password:
            return None
        if self.verify_superadmin_password(password):
            return {"role": "superadmin", "username": None}
        for username, cfg in self._data["accounts"].items():
            if not cfg.get("enabled", True) or self._is_expired(cfg):
                continue
            if self._verify_hash(password, cfg["login_hash"]):
                return {"role": "account", "username": username}
        return None

    def verify_account_ability(self, username, ability, password):
        account = self._data["accounts"].get(username)
        if account is None or ability not in ACCOUNT_ABILITIES:
            return False
        return self._verify_hash(password, account[f"{ability}_hash"])

    def abilities_matching(self, username, password):
        """返回某个密码同时匹配到的操作能力。

        用于登录时判断：若登录密码与下载/删除密码相同，则免去二次输入。
        """
        account = self._data["accounts"].get(username)
        if account is None or not password:
            return []
        return [
            ability
            for ability in ACCOUNT_ABILITIES
            if self._verify_hash(password, account[f"{ability}_hash"])
        ]

    # ---------------- 令牌 ----------------
    def _sign(self, payload):
        raw = base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":")).encode("utf-8")
        ).decode("utf-8")
        sig = hmac.new(self.secret_key, raw.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"{raw}.{sig}"

    def _unsign(self, token):
        if not token or "." not in token:
            return None
        try:
            raw, sig = token.split(".", 1)
            expected = hmac.new(self.secret_key, raw.encode("utf-8"), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(sig, expected):
                return None
            return json.loads(base64.urlsafe_b64decode(raw.encode("utf-8")).decode("utf-8"))
        except Exception:
            return None

    def issue_session_token(self, username, ttl_seconds):
        account = self._data["accounts"].get(username)
        if account is None:
            return ""
        return self._sign(
            {"role": "account", "user": username, "exp": int(time.time()) + ttl_seconds, "ver": account["version"]}
        )

    def verify_session_token(self, token):
        payload = self._unsign(token)
        if not payload or payload.get("role") != "account":
            return None
        if payload.get("exp", 0) < int(time.time()):
            return None
        account = self._data["accounts"].get(payload.get("user"))
        if account is None or not account.get("enabled", True) or self._is_expired(account):
            return None
        if payload.get("ver") != account["version"]:
            return None
        return payload["user"]

    def issue_admin_token(self, ttl_seconds):
        return self._sign(
            {"role": "superadmin", "exp": int(time.time()) + ttl_seconds, "ver": self._data["superadmin"]["version"]}
        )

    def verify_admin_token(self, token):
        payload = self._unsign(token)
        if not payload or payload.get("role") != "superadmin":
            return False
        if payload.get("exp", 0) < int(time.time()):
            return False
        return payload.get("ver") == self._data["superadmin"]["version"]

    def issue_ability_token(self, username, ability, ttl_seconds):
        account = self._data["accounts"].get(username)
        if account is None or ability not in ACCOUNT_ABILITIES:
            return ""
        return self._sign(
            {
                "role": "ability",
                "user": username,
                "ability": ability,
                "exp": int(time.time()) + ttl_seconds,
                "ver": account["version"],
            }
        )

    def verify_ability_token(self, username, ability, token):
        payload = self._unsign(token)
        if not payload or payload.get("role") != "ability":
            return False
        if payload.get("user") != username or payload.get("ability") != ability:
            return False
        if payload.get("exp", 0) < int(time.time()):
            return False
        account = self._data["accounts"].get(username)
        return bool(account) and payload.get("ver") == account["version"]


# ---------------- Flask 集成 ----------------
def get_account_manager():
    return current_app.config["PASSWORD_MANAGER"]


def current_account():
    return get_account_manager().verify_session_token(request.cookies.get(SESSION_COOKIE, ""))


def is_superadmin():
    return get_account_manager().verify_admin_token(request.cookies.get(ADMIN_COOKIE, ""))


def has_ability(ability, username):
    token = request.cookies.get(ABILITY_COOKIES.get(ability, ""), "")
    return get_account_manager().verify_ability_token(username, ability, token)


def require_account_session(page_redirect=False):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            username = current_account()
            if username:
                g.account = username
                return view(*args, **kwargs)
            if page_redirect:
                next_url = request.full_path.rstrip("?")
                return redirect(f"/login?next={next_url}")
            return jsonify({"status": 1, "message": "需要登录", "need_auth": "login"}), 401

        return wrapped

    return decorator


def require_ability(ability):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            username = current_account()
            if username and has_ability(ability, username):
                g.account = username
                return view(*args, **kwargs)
            return jsonify({"status": 1, "message": "需要密码", "need_auth": ability}), 401

        return wrapped

    return decorator


def require_superadmin(page_redirect=False):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if is_superadmin():
                return view(*args, **kwargs)
            if page_redirect:
                next_url = request.full_path.rstrip("?")
                return redirect(f"/login?next={next_url}")
            return jsonify({"status": 1, "message": "需要超级管理员权限", "need_auth": "admin"}), 401

        return wrapped

    return decorator
