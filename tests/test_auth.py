from datetime import datetime, timedelta

import pytest

from netu_app.auth import (
    DEFAULT_ACCOUNT_EXPIRE_DAYS,
    EXPIRE_FORMAT,
    AccountManager,
    compute_expires_at,
    expires_at_passed,
    parse_expire_days,
)


def build_manager(tmp_path):
    return AccountManager(tmp_path / ".passwords.yaml", "secret-key")


def expire_account(manager, username, moments_ago=timedelta(days=1)):
    """把账户到期时间改到过去，模拟有效期已过。"""
    manager._data["accounts"][username]["expires_at"] = (
        datetime.now() - moments_ago
    ).strftime(EXPIRE_FORMAT)
    manager._save(manager._data)


def test_default_superadmin_password_matches(tmp_path):
    manager = build_manager(tmp_path)

    assert manager.verify_superadmin_password("7bef9fb4b0") is True
    assert manager.match_login("7bef9fb4b0") == {"role": "superadmin", "username": None}


def test_legacy_plaintext_config_is_migrated(tmp_path):
    config_path = tmp_path / ".passwords.yaml"
    config_path.write_text(
        "passwords:\n  open: 7bef\n  admin: 7bef\n",
        encoding="utf-8",
    )

    manager = AccountManager(config_path, "secret-key")

    assert manager.verify_superadmin_password("7bef") is True
    migrated = config_path.read_text(encoding="utf-8")
    assert "accounts:" in migrated
    assert "pbkdf2_sha256$" in migrated


def test_create_account_and_match_login(tmp_path):
    manager = build_manager(tmp_path)
    manager.create_account("alice", "alice-login", "alice-dl", "alice-del")

    assert manager.match_login("alice-login") == {"role": "account", "username": "alice"}
    assert manager.match_login("nope") is None


def test_login_password_must_be_unique_across_accounts(tmp_path):
    manager = build_manager(tmp_path)
    manager.create_account("alice", "shared-login", "alice-dl", "alice-del")

    with pytest.raises(ValueError):
        manager.create_account("bob", "shared-login", "bob-dl", "bob-del")


def test_login_password_cannot_equal_superadmin_password(tmp_path):
    manager = build_manager(tmp_path)

    with pytest.raises(ValueError):
        manager.create_account("alice", "7bef9fb4b0", "alice-dl", "alice-del")


def test_invalid_username_is_rejected(tmp_path):
    manager = build_manager(tmp_path)

    for bad_name in ("", "admin", "root", "has space", "with/slash"):
        with pytest.raises(ValueError):
            manager.create_account(bad_name, "abc123", "abc123", "abc123")


def test_ability_verification(tmp_path):
    manager = build_manager(tmp_path)
    manager.create_account("alice", "alice-login", "alice-dl", "alice-del")

    assert manager.verify_account_ability("alice", "download", "alice-dl") is True
    assert manager.verify_account_ability("alice", "delete", "alice-del") is True
    assert manager.verify_account_ability("alice", "download", "wrong") is False
    assert manager.verify_account_ability("ghost", "download", "alice-dl") is False


def test_abilities_matching_detects_shared_passwords(tmp_path):
    manager = build_manager(tmp_path)
    manager.create_account("alice", "shared-pass", "shared-pass", "other-del")

    assert manager.abilities_matching("alice", "shared-pass") == ["download"]
    assert manager.abilities_matching("alice", "other-del") == ["delete"]
    assert manager.abilities_matching("alice", "nope") == []
    assert manager.abilities_matching("ghost", "shared-pass") == []


def test_list_accounts_exposes_stored_passwords(tmp_path):
    manager = build_manager(tmp_path)
    manager.create_account("alice", "alice-login", "alice-dl", "alice-del")

    listing = manager.list_accounts()

    assert listing[0]["login_password"] == "alice-login"
    assert listing[0]["download_password"] == "alice-dl"
    assert listing[0]["delete_password"] == "alice-del"
    assert listing[0]["passwords_visible"] is True


def test_session_token_invalidates_after_password_change(tmp_path):
    manager = build_manager(tmp_path)
    manager.create_account("alice", "alice-login", "alice-dl", "alice-del")
    token = manager.issue_session_token("alice", ttl_seconds=3600)

    assert manager.verify_session_token(token) == "alice"

    manager.update_account("alice", login_password="new-login")

    assert manager.verify_session_token(token) is None


def test_admin_token_invalidates_after_superadmin_change(tmp_path):
    manager = build_manager(tmp_path)
    token = manager.issue_admin_token(ttl_seconds=3600)

    assert manager.verify_admin_token(token) is True

    manager.set_superadmin_password("new-admin-pass")

    assert manager.verify_admin_token(token) is False


def test_disabled_account_cannot_login(tmp_path):
    manager = build_manager(tmp_path)
    manager.create_account("alice", "alice-login", "alice-dl", "alice-del")

    manager.update_account("alice", enabled=False)

    assert manager.match_login("alice-login") is None


def test_remove_account(tmp_path):
    manager = build_manager(tmp_path)
    manager.create_account("alice", "alice-login", "alice-dl", "alice-del")

    assert manager.remove_account("alice") is True
    assert manager.remove_account("alice") is False
    assert manager.match_login("alice-login") is None


def test_parse_expire_days_normalizes_input():
    assert parse_expire_days(None) == 0
    assert parse_expire_days("abc") == 0
    assert parse_expire_days(-5) == 0
    assert parse_expire_days("15") == 15


def test_compute_expires_at_respects_zero_and_days():
    assert compute_expires_at(0) == ""

    base = datetime(2026, 1, 1, 8, 0)
    assert compute_expires_at(30, base=base) == (base + timedelta(days=30)).strftime(EXPIRE_FORMAT)


def test_expires_at_passed_handles_empty_and_future():
    assert expires_at_passed("") is False
    assert expires_at_passed("not-a-date") is False
    assert expires_at_passed(compute_expires_at(1)) is False
    assert expires_at_passed((datetime.now() - timedelta(minutes=1)).strftime(EXPIRE_FORMAT)) is True


def test_create_account_defaults_to_30_day_expiry(tmp_path):
    manager = build_manager(tmp_path)
    manager.create_account("alice", "alice-login", "alice-dl", "alice-del")

    listing = manager.list_accounts()[0]

    assert listing["expire_days"] == DEFAULT_ACCOUNT_EXPIRE_DAYS == 30
    assert listing["expires_at"] != ""
    assert listing["expired"] is False


def test_create_account_accepts_custom_expire_days(tmp_path):
    manager = build_manager(tmp_path)
    manager.create_account("alice", "alice-login", "alice-dl", "alice-del", expire_days=7)

    assert manager.list_accounts()[0]["expire_days"] == 7


def test_create_account_with_zero_never_expires(tmp_path):
    manager = build_manager(tmp_path)
    manager.create_account("alice", "alice-login", "alice-dl", "alice-del", expire_days=0)

    listing = manager.list_accounts()[0]

    assert listing["expire_days"] == 0
    assert listing["expires_at"] == ""
    assert listing["expired"] is False


def test_expired_account_cannot_login(tmp_path):
    manager = build_manager(tmp_path)
    manager.create_account("alice", "alice-login", "alice-dl", "alice-del")
    token = manager.issue_session_token("alice", ttl_seconds=3600)

    expire_account(manager, "alice")

    assert manager.match_login("alice-login") is None
    assert manager.verify_session_token(token) is None
    assert manager.list_accounts()[0]["expired"] is True


def test_update_account_refreshes_expiry_when_days_change(tmp_path):
    manager = build_manager(tmp_path)
    manager.create_account("alice", "alice-login", "alice-dl", "alice-del", expire_days=30)

    changed = manager.update_account("alice", expire_days=90)

    assert changed is True
    assert manager.list_accounts()[0]["expire_days"] == 90


def test_update_account_recomputes_expiry_even_when_days_unchanged(tmp_path):
    manager = build_manager(tmp_path)
    manager.create_account("alice", "alice-login", "alice-dl", "alice-del", expire_days=30)
    # 模拟历史数据：天数仍是 30，但没有（或已失效的）到期时间。
    manager._data["accounts"]["alice"]["expires_at"] = ""
    manager._save(manager._data)

    manager.update_account("alice", expire_days=30)

    listing = manager.list_accounts()[0]
    assert listing["expires_at"] != ""
    assert listing["expired"] is False


def test_update_account_ignores_expiry_when_not_provided(tmp_path):
    manager = build_manager(tmp_path)
    manager.create_account("alice", "alice-login", "alice-dl", "alice-del", expire_days=15)
    original = manager.list_accounts()[0]["expires_at"]

    manager.update_account("alice", login_password="new-login")

    assert manager.list_accounts()[0]["expires_at"] == original


def test_update_account_expiry_change_reactivates_expired_account(tmp_path):
    manager = build_manager(tmp_path)
    manager.create_account("alice", "alice-login", "alice-dl", "alice-del", expire_days=1)
    expire_account(manager, "alice")

    manager.update_account("alice", expire_days=30)

    assert manager.list_accounts()[0]["expired"] is False
    assert manager.match_login("alice-login") == {"role": "account", "username": "alice"}
