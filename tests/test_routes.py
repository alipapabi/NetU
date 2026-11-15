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


def add_account(app, username="alice", login="alice-login", download="alice-dl", delete="alice-del"):
    app.config["PASSWORD_MANAGER"].create_account(username, login, download, delete)


def login(client, password):
    return client.post("/login", json={"password": password})


def upload(client, name="a.txt", content=b"hello"):
    return client.post(
        "/api/upload",
        data={"file": (BytesIO(content), name)},
        content_type="multipart/form-data",
    )


def test_index_redirects_to_login(tmp_path):
    app = build_app(tmp_path)
    client = app.test_client()

    response = client.get("/")

    assert response.status_code == 302
    assert response.headers["Location"].startswith("/login")


def test_login_page_contains_password_form(tmp_path):
    app = build_app(tmp_path)
    client = app.test_client()

    response = client.get("/login")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'name="password"' in body
    assert "NetU" in body


def test_account_login_sets_session_cookie(tmp_path):
    app = build_app(tmp_path)
    add_account(app)
    client = app.test_client()

    response = client.post(
        "/login",
        data={"password": "alice-login", "next": "/"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert any("netu_session=" in header for header in response.headers.getlist("Set-Cookie"))


def test_superadmin_json_login_redirects_to_admin(tmp_path):
    app = build_app(tmp_path)
    client = app.test_client()

    response = client.post("/login", json={"password": "7bef9fb4b0"})
    body = response.get_json()

    assert response.status_code == 200
    assert body["role"] == "superadmin"
    assert body["redirect"] == "/admin"
    assert any("netu_admin=" in header for header in response.headers.getlist("Set-Cookie"))


def test_wrong_password_redirects_with_error(tmp_path):
    app = build_app(tmp_path)
    client = app.test_client()

    response = client.post("/login", data={"password": "wrong"}, follow_redirects=False)

    assert response.status_code == 302
    assert "/login?e=1" in response.headers["Location"]


def test_api_session_returns_username_and_capabilities(tmp_path):
    app = build_app(tmp_path)
    add_account(app)
    client = app.test_client()
    login(client, "alice-login")

    body = client.get("/api/session").get_json()

    assert body["username"] == "alice"
    assert body["capabilities"] == {"download": False, "delete": False}


def test_login_grants_abilities_when_passwords_match(tmp_path):
    app = build_app(tmp_path)
    app.config["PASSWORD_MANAGER"].create_account("alice", "same-pass", "same-pass", "same-pass")
    client = app.test_client()

    response = client.post("/login", json={"password": "same-pass"})
    cookies = response.headers.getlist("Set-Cookie")

    assert any("netu_download=" in header for header in cookies)
    assert any("netu_delete=" in header for header in cookies)

    body = client.get("/api/session").get_json()
    assert body["capabilities"] == {"download": True, "delete": True}


def test_download_allowed_without_unlock_when_login_matches(tmp_path):
    app = build_app(tmp_path)
    app.config["PASSWORD_MANAGER"].create_account("alice", "same-pass", "same-pass", "same-pass")
    client = app.test_client()
    login(client, "same-pass")
    upload(client, "a.txt", b"hello")

    response = client.get("/download/a.txt")

    assert response.status_code == 200
    assert response.data == b"hello"


def test_upload_requires_login(tmp_path):
    app = build_app(tmp_path)
    client = app.test_client()

    response = upload(client)

    assert response.status_code == 401


def test_files_are_isolated_per_account(tmp_path):
    app = build_app(tmp_path)
    add_account(app, "alice", "alice-login", "alice-dl", "alice-del")
    add_account(app, "bob", "bob-login", "bob-dl", "bob-del")
    client = app.test_client()
    login(client, "alice-login")

    upload(client, "a.txt")

    assert (tmp_path / "down" / "alice" / "a.txt").exists()
    assert not (tmp_path / "down" / "bob" / "a.txt").exists()
    payload = client.get("/api/files").get_json()
    assert payload["files"][0]["name"] == "a.txt"


def test_delete_hides_file_and_requires_delete_password(tmp_path):
    app = build_app(tmp_path)
    add_account(app)
    client = app.test_client()
    login(client, "alice-login")
    upload(client, "a.txt")

    denied = client.post("/api/delete", json={"filename": "a.txt"})
    assert denied.status_code == 401
    assert denied.get_json()["need_auth"] == "delete"

    unlock = client.post("/api/unlock", json={"ability": "delete", "password": "alice-del"})
    assert unlock.status_code == 200

    deleted = client.post("/api/delete", json={"filename": "a.txt"})
    assert deleted.status_code == 200
    assert not (tmp_path / "down" / "alice" / "a.txt").exists()
    assert (tmp_path / "down" / "alice" / ".hidden" / "a.txt").exists()

    payload = client.get("/api/files").get_json()
    assert payload["files"] == []
    assert "hidden" not in payload


def test_regular_user_cannot_restore_hidden_file(tmp_path):
    app = build_app(tmp_path)
    add_account(app)
    client = app.test_client()
    login(client, "alice-login")
    upload(client, "a.txt")
    client.post("/api/unlock", json={"ability": "delete", "password": "alice-del"})
    client.post("/api/delete", json={"filename": "a.txt"})

    response = client.post("/api/restore", json={"filename": "a.txt"})

    assert response.status_code == 404
    assert not (tmp_path / "down" / "alice" / "a.txt").exists()
    assert (tmp_path / "down" / "alice" / ".hidden" / "a.txt").exists()


def test_download_requires_download_ability(tmp_path):
    app = build_app(tmp_path)
    add_account(app)
    client = app.test_client()
    login(client, "alice-login")
    upload(client, "a.txt", b"hello")

    denied = client.get("/download/a.txt")
    assert denied.status_code == 302
    assert "/?denied=download" in denied.headers["Location"]

    client.post("/api/unlock", json={"ability": "download", "password": "alice-dl"})
    allowed = client.get("/download/a.txt")
    assert allowed.status_code == 200
    assert allowed.data == b"hello"


def test_api_files_changed_false_when_etag_matches(tmp_path):
    app = build_app(tmp_path)
    add_account(app)
    client = app.test_client()
    login(client, "alice-login")
    upload(client, "a.txt")

    first = client.get("/api/files").get_json()
    second = client.get(f"/api/files?since={first['etag']}").get_json()

    assert first["changed"] is True
    assert second["changed"] is False
    assert second["etag"] == first["etag"]


def test_view_renders_text_preview(tmp_path):
    app = build_app(tmp_path)
    add_account(app)
    client = app.test_client()
    login(client, "alice-login")
    upload(client, "notes.txt", b"hello preview")

    response = client.get("/view/notes.txt")

    assert response.status_code == 200
    assert "hello preview" in response.get_data(as_text=True)


def test_view_renders_rich_preview_page(tmp_path):
    app = build_app(tmp_path)
    add_account(app)
    client = app.test_client()
    login(client, "alice-login")
    upload(client, "doc.md", "# 标题\n\n正文".encode("utf-8"))

    body = client.get("/view/doc.md").get_data(as_text=True)

    assert "preview-topbar" in body
    assert "<h1>标题</h1>" in body
    assert "/download/doc.md" in body


def test_view_renders_csv_table(tmp_path):
    app = build_app(tmp_path)
    add_account(app)
    client = app.test_client()
    login(client, "alice-login")
    upload(client, "data.csv", b"name,age\nalice,30\n")

    body = client.get("/view/data.csv").get_data(as_text=True)

    assert "<th>name</th>" in body
    assert "<td>alice</td>" in body


def test_view_unknown_format_shows_download_hint(tmp_path):
    app = build_app(tmp_path)
    add_account(app)
    client = app.test_client()
    login(client, "alice-login")
    upload(client, "bundle.bin", b"\x00\x01\x02")

    body = client.get("/view/bundle.bin").get_data(as_text=True)

    assert "暂不支持在线预览" in body


def test_account_note_round_trip_and_session(tmp_path):
    app = build_app(tmp_path)
    add_account(app)
    client = app.test_client()
    login(client, "alice-login")

    assert client.get("/api/session").get_json()["note"] == ""

    saved = client.post("/api/account-note", json={"note": "给 alice 的临时区"})

    assert saved.status_code == 200
    assert saved.get_json()["note"] == "给 alice 的临时区"
    assert client.get("/api/session").get_json()["note"] == "给 alice 的临时区"


def test_file_note_is_saved_and_returned(tmp_path):
    app = build_app(tmp_path)
    add_account(app)
    client = app.test_client()
    login(client, "alice-login")
    upload(client, "a.txt")

    saved = client.post("/api/note", json={"filename": "a.txt", "note": "第一条备注"})

    assert saved.status_code == 200
    payload = client.get("/api/files").get_json()
    assert payload["files"][0]["note"] == "第一条备注"

    assert client.post("/api/note", json={"filename": "ghost.txt", "note": "x"}).status_code == 404


def test_note_endpoints_require_login(tmp_path):
    app = build_app(tmp_path)
    client = app.test_client()

    assert client.post("/api/account-note", json={"note": "x"}).status_code == 401
    assert client.post("/api/note", json={"filename": "a.txt", "note": "x"}).status_code == 401
