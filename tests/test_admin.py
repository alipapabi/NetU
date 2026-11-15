from io import BytesIO

from netu_app import create_app


def build_app(tmp_path):
    return create_app(
        {
            "TESTING": True,
            "NETU_DOWN_DIR": str(tmp_path / "down"),
            "NETU_CONFIG": str(tmp_path / ".passwords.yaml"),
            "NETU_SECRET": "secret-key",
        }
    )


def login_admin(client):
    return client.post("/login", json={"password": "7bef9fb4b0"})


def create_account(client, username="alice", login="alice-login", download="alice-dl", delete="alice-del"):
    return client.post(
        "/admin/api/accounts",
        json={
            "username": username,
            "login_password": login,
            "download_password": download,
            "delete_password": delete,
        },
    )


def admin_upload(client, owner, name="a.txt", content=b"hello"):
    return client.post(
        f"/admin/api/upload?owner={owner}",
        data={"file": (BytesIO(content), name)},
        content_type="multipart/form-data",
    )


def test_admin_requires_superadmin(tmp_path):
    app = build_app(tmp_path)
    client = app.test_client()

    response = client.get("/admin")

    assert response.status_code == 302
    assert response.headers["Location"].startswith("/login")


def test_admin_page_renders_settings_form(tmp_path):
    app = build_app(tmp_path)
    client = app.test_client()
    login_admin(client)

    response = client.get("/admin")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'id="cookieTtlDays"' in body
    assert "超级管理员" in body
    assert 'id="accountList"' in body
    assert 'id="ownerSelect"' in body
    assert 'id="accountExpireDays"' in body
    assert 'id="statFiles"' in body
    assert 'id="fileSearch"' in body
    assert 'id="fileSort"' in body
    assert 'data-tab="accounts"' in body
    assert 'data-tab="files"' in body
    assert 'data-tab="security"' in body


def test_admin_can_create_and_list_accounts(tmp_path):
    app = build_app(tmp_path)
    client = app.test_client()
    login_admin(client)

    response = create_account(client)
    assert response.status_code == 200

    listing = client.get("/admin/api/accounts").get_json()["accounts"]
    assert [account["username"] for account in listing] == ["alice"]
    assert listing[0]["enabled"] is True


def test_admin_can_create_account_with_expire_days(tmp_path):
    app = build_app(tmp_path)
    client = app.test_client()
    login_admin(client)

    response = client.post(
        "/admin/api/accounts",
        json={
            "username": "alice",
            "login_password": "alice-login",
            "download_password": "alice-dl",
            "delete_password": "alice-del",
            "expire_days": 7,
        },
    )

    assert response.status_code == 200
    listing = client.get("/admin/api/accounts").get_json()["accounts"]
    assert listing[0]["expire_days"] == 7
    assert listing[0]["expires_at"] != ""
    assert listing[0]["expired"] is False


def test_admin_can_update_account_expire_days(tmp_path):
    app = build_app(tmp_path)
    client = app.test_client()
    login_admin(client)
    create_account(client)

    response = client.post("/admin/api/accounts/alice", json={"expire_days": 90})

    assert response.status_code == 200
    listing = client.get("/admin/api/accounts").get_json()["accounts"]
    assert listing[0]["expire_days"] == 90


def test_create_account_validation_error(tmp_path):
    app = build_app(tmp_path)
    client = app.test_client()
    login_admin(client)

    response = create_account(client, username="root")

    assert response.status_code == 400
    assert response.get_json()["status"] == 1


def test_admin_can_update_account_password(tmp_path):
    app = build_app(tmp_path)
    client = app.test_client()
    login_admin(client)
    create_account(client)

    response = client.post(
        "/admin/api/accounts/alice",
        json={"login_password": "alice-new-login"},
    )

    assert response.status_code == 200
    manager = app.config["PASSWORD_MANAGER"]
    assert manager.match_login("alice-new-login") == {"role": "account", "username": "alice"}


def test_admin_can_disable_account(tmp_path):
    app = build_app(tmp_path)
    client = app.test_client()
    login_admin(client)
    create_account(client)

    client.post("/admin/api/accounts/alice", json={"enabled": False})

    listing = client.get("/admin/api/accounts").get_json()["accounts"]
    assert listing[0]["enabled"] is False


def test_admin_delete_account_moves_files_to_trash(tmp_path):
    app = build_app(tmp_path)
    client = app.test_client()
    login_admin(client)
    create_account(client)
    admin_upload(client, "alice", "a.txt")

    response = client.delete("/admin/api/accounts/alice")

    assert response.status_code == 200
    assert not (tmp_path / "down" / "alice").exists()
    trash = tmp_path / "down" / ".trash"
    moved = list(trash.iterdir())
    assert len(moved) == 1
    assert (moved[0] / "a.txt").exists()
    assert client.get("/admin/api/accounts").get_json()["accounts"] == []


def test_admin_can_upload_to_specific_owner(tmp_path):
    app = build_app(tmp_path)
    client = app.test_client()
    login_admin(client)
    create_account(client)

    response = admin_upload(client, "alice", "report.txt")

    assert response.status_code == 200
    assert (tmp_path / "down" / "alice" / "report.txt").exists()


def test_admin_files_rejects_unknown_owner(tmp_path):
    app = build_app(tmp_path)
    client = app.test_client()
    login_admin(client)

    response = client.get("/admin/api/files?owner=ghost")

    assert response.status_code == 404


def test_admin_aggregate_files_annotate_owner(tmp_path):
    app = build_app(tmp_path)
    client = app.test_client()
    login_admin(client)
    create_account(client)
    admin_upload(client, "alice", "a.txt")
    admin_upload(client, "root", "root.txt")

    payload = client.get("/admin/api/files?owner=all").get_json()

    assert payload["changed"] is True
    owners = {item["name"]: item["owner"] for item in payload["files"]}
    assert owners["a.txt"] == "alice"
    assert owners["root.txt"] == "root"


def test_admin_account_listing_exposes_stored_passwords(tmp_path):
    app = build_app(tmp_path)
    client = app.test_client()
    login_admin(client)
    create_account(client)

    listing = client.get("/admin/api/accounts").get_json()["accounts"]

    assert listing[0]["login_password"] == "alice-login"
    assert listing[0]["download_password"] == "alice-dl"
    assert listing[0]["delete_password"] == "alice-del"


def test_admin_update_with_empty_password_keeps_original(tmp_path):
    app = build_app(tmp_path)
    client = app.test_client()
    login_admin(client)
    create_account(client)

    response = client.post("/admin/api/accounts/alice", json={"login_password": ""})

    assert response.status_code == 200
    manager = app.config["PASSWORD_MANAGER"]
    assert manager.match_login("alice-login") == {"role": "account", "username": "alice"}


def test_admin_can_hide_and_purge_file(tmp_path):
    app = build_app(tmp_path)
    client = app.test_client()
    login_admin(client)
    create_account(client)
    admin_upload(client, "alice", "a.txt")

    hidden = client.post("/admin/api/delete", json={"owner": "alice", "filename": "a.txt", "mode": "hide"})
    assert hidden.status_code == 200
    assert (tmp_path / "down" / "alice" / ".hidden" / "a.txt").exists()

    purged = client.post("/admin/api/delete", json={"owner": "alice", "filename": "a.txt", "mode": "purge"})
    assert purged.status_code == 200
    assert not (tmp_path / "down" / "alice" / ".hidden" / "a.txt").exists()


def test_admin_can_restore_hidden_file(tmp_path):
    app = build_app(tmp_path)
    client = app.test_client()
    login_admin(client)
    create_account(client)
    admin_upload(client, "alice", "a.txt")
    client.post("/admin/api/delete", json={"owner": "alice", "filename": "a.txt", "mode": "hide"})

    response = client.post("/admin/api/restore", json={"owner": "alice", "filename": "a.txt"})

    assert response.status_code == 200
    assert (tmp_path / "down" / "alice" / "a.txt").exists()


def test_admin_can_set_account_note(tmp_path):
    app = build_app(tmp_path)
    client = app.test_client()
    login_admin(client)
    create_account(client)

    saved = client.post("/admin/api/accounts/alice/note", json={"note": "给 alice 的备注"})

    assert saved.status_code == 200
    assert app.config["PASSWORD_MANAGER"].get_account("alice")["note"] == "给 alice 的备注"
    listing = client.get("/admin/api/accounts").get_json()["accounts"]
    assert listing[0]["note"] == "给 alice 的备注"


def test_admin_can_set_file_note_for_owner(tmp_path):
    app = build_app(tmp_path)
    client = app.test_client()
    login_admin(client)
    create_account(client)
    admin_upload(client, "alice", "a.txt")

    saved = client.post(
        "/admin/api/note?owner=alice",
        json={"filename": "a.txt", "note": "管理员备注"},
    )

    assert saved.status_code == 200
    payload = client.get("/admin/api/files?owner=alice").get_json()
    assert payload["files"][0]["note"] == "管理员备注"

    missing = client.post("/admin/api/note?owner=alice", json={"filename": "ghost.txt", "note": "x"})
    assert missing.status_code == 404


def test_admin_can_update_cookie_ttl(tmp_path):
    app = build_app(tmp_path)
    client = app.test_client()
    login_admin(client)

    response = client.post("/admin/api/security", json={"cookie_ttl_days": 3})

    assert response.status_code == 200
    assert app.config["PASSWORD_MANAGER"].get_security_settings()["cookie_ttl_days"] == 3


def test_admin_file_view_renders_preview_page(tmp_path):
    app = build_app(tmp_path)
    client = app.test_client()
    login_admin(client)
    create_account(client)
    admin_upload(client, "alice", "notes.md", "# 标题\n\n内容".encode("utf-8"))

    body = client.get("/admin/file/view?owner=alice&filename=notes.md").get_data(as_text=True)

    assert "preview-topbar" in body
    assert "<h1>标题</h1>" in body
    assert "/admin/file/download?owner=alice&amp;filename=notes.md" in body


def test_admin_file_view_unknown_owner_returns_404(tmp_path):
    app = build_app(tmp_path)
    client = app.test_client()
    login_admin(client)

    response = client.get("/admin/file/view?owner=ghost&filename=a.txt")

    assert response.status_code == 404


def test_change_superadmin_password_invalidates_admin_cookie(tmp_path):
    app = build_app(tmp_path)
    client = app.test_client()
    login_admin(client)

    response = client.post("/admin/api/superadmin", json={"password": "new-admin-pass"})
    assert response.status_code == 200

    assert client.get("/admin").status_code == 302
    assert app.config["PASSWORD_MANAGER"].verify_superadmin_password("new-admin-pass") is True
