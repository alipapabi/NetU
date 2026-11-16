from io import BytesIO

from netu_app import create_app
from netu_app.activity import ActivityLog


def build_app(tmp_path, **overrides):
    config = {
        "TESTING": True,
        "NETU_DOWN_DIR": str(tmp_path / "down"),
        "NETU_CONFIG": str(tmp_path / ".passwords.yaml"),
        "NETU_SECRET": "secret-key",
    }
    config.update(overrides)
    return create_app(config)


def login(client, password):
    return client.post("/login", json={"password": password})


def login_admin(client):
    return client.post("/login", json={"password": "admin888"})


def upload(client, name="a.txt", content=b"hello"):
    return client.post(
        "/api/upload",
        data={"file": (BytesIO(content), name)},
        content_type="multipart/form-data",
    )


def actions_for(app, username):
    return [record["action"] for record in app.config["ACTIVITY_LOG"].list_records(username)]


# ---------------- ActivityLog 单元 ----------------
def test_activity_log_keeps_newest_first(tmp_path):
    log = ActivityLog(tmp_path / "activity.jsonl")
    log.record("alice", "login")
    log.record("alice", "upload", "a.txt")
    log.record("bob", "login")

    records = log.list_records()

    assert [record["action"] for record in records] == ["login", "upload", "login"]
    assert records[0]["username"] == "bob"
    assert records[-1]["username"] == "alice"


def test_activity_log_filters_by_username(tmp_path):
    log = ActivityLog(tmp_path / "activity.jsonl")
    log.record("alice", "login")
    log.record("bob", "login")

    assert [record["username"] for record in log.list_records("alice")] == ["alice"]
    assert len(log.list_records()) == 2


def test_activity_log_clear_by_username(tmp_path):
    log = ActivityLog(tmp_path / "activity.jsonl")
    log.record("alice", "login")
    log.record("bob", "login")

    removed = log.clear("alice")

    assert removed == 1
    assert [record["username"] for record in log.list_records()] == ["bob"]


def test_activity_log_clear_all(tmp_path):
    log = ActivityLog(tmp_path / "activity.jsonl")
    log.record("alice", "login")
    log.record("bob", "login")

    log.clear()

    assert log.list_records() == []
    assert log.path.read_text(encoding="utf-8") == ""


def test_activity_log_trims_to_max_entries(tmp_path):
    log = ActivityLog(tmp_path / "activity.jsonl", max_entries=10)
    for index in range(100):
        log.record("alice", "upload", f"f{index}.txt")

    records = log.list_records()

    assert records[0]["filename"] == "f99.txt"
    assert len(records) <= 10 + log.trim_margin


def test_activity_log_ignores_unknown_action(tmp_path):
    log = ActivityLog(tmp_path / "activity.jsonl")

    assert log.record("alice", "preview", "a.txt") is None
    assert log.list_records() == []


# ---------------- 埋点：用户行为 ----------------
def test_user_login_upload_download_delete_are_recorded(tmp_path):
    app = build_app(tmp_path)
    app.config["PASSWORD_MANAGER"].create_account("alice", "same-pass", "same-pass", "same-pass")
    client = app.test_client()

    login(client, "same-pass")
    upload(client, "a.txt", b"hello")
    client.get("/download/a.txt")
    client.post("/api/delete", json={"filename": "a.txt"})

    records = app.config["ACTIVITY_LOG"].list_records("alice")
    assert [record["action"] for record in records] == ["delete", "download", "upload", "login"]
    assert records[2]["filename"] == "a.txt"
    assert records[2]["ip"] == "127.0.0.1"


def test_failed_login_is_not_recorded(tmp_path):
    app = build_app(tmp_path)
    client = app.test_client()

    login(client, "wrong")

    assert app.config["ACTIVITY_LOG"].list_records() == []


def test_denied_download_is_not_recorded(tmp_path):
    app = build_app(tmp_path)
    app.config["PASSWORD_MANAGER"].create_account("alice", "alice-login", "alice-dl", "alice-del")
    client = app.test_client()
    login(client, "alice-login")
    upload(client, "a.txt")

    client.get("/download/a.txt")

    assert "download" not in actions_for(app, "alice")


def test_superadmin_actions_are_recorded_under_superadmin(tmp_path):
    app = build_app(tmp_path)
    client = app.test_client()
    login_admin(client)
    client.post(
        "/admin/api/upload?owner=root",
        data={"file": (BytesIO(b"hi"), "a.txt")},
        content_type="multipart/form-data",
    )
    client.get("/admin/file/download?owner=root&filename=a.txt")
    client.post("/admin/api/delete", json={"owner": "root", "filename": "a.txt", "mode": "hide"})

    assert actions_for(app, "superadmin") == ["delete", "download", "upload", "login"]


# ---------------- 接口 ----------------
def test_activity_api_requires_superadmin(tmp_path):
    app = build_app(tmp_path)
    client = app.test_client()

    assert client.get("/admin/api/activity").status_code == 401
    assert client.post("/admin/api/activity/clear", json={"scope": "all"}).status_code == 401


def test_activity_api_lists_records_with_labels(tmp_path):
    app = build_app(tmp_path)
    app.config["PASSWORD_MANAGER"].create_account("alice", "alice-login", "alice-dl", "alice-del")
    login(app.test_client(), "alice-login")

    admin = app.test_client()
    login_admin(admin)

    body = admin.get("/admin/api/activity?username=alice").get_json()

    assert body["status"] == 0
    assert len(body["records"]) == 1
    assert body["records"][0]["action"] == "login"
    assert body["records"][0]["action_label"] == "登录"


def test_activity_api_clears_single_account_only(tmp_path):
    app = build_app(tmp_path)
    app.config["PASSWORD_MANAGER"].create_account("alice", "alice-login", "alice-dl", "alice-del")
    login(app.test_client(), "alice-login")

    admin = app.test_client()
    login_admin(admin)

    cleared = admin.post("/admin/api/activity/clear", json={"scope": "account", "username": "alice"})

    assert cleared.status_code == 200
    assert admin.get("/admin/api/activity?username=alice").get_json()["records"] == []
    assert len(admin.get("/admin/api/activity?username=superadmin").get_json()["records"]) == 1


def test_activity_api_clear_all(tmp_path):
    app = build_app(tmp_path)
    app.config["PASSWORD_MANAGER"].create_account("alice", "alice-login", "alice-dl", "alice-del")
    login(app.test_client(), "alice-login")

    admin = app.test_client()
    login_admin(admin)

    cleared = admin.post("/admin/api/activity/clear", json={"scope": "all"})

    assert cleared.status_code == 200
    assert admin.get("/admin/api/activity").get_json()["records"] == []


def test_activity_api_clear_requires_username_for_account_scope(tmp_path):
    app = build_app(tmp_path)
    admin = app.test_client()
    login_admin(admin)

    response = admin.post("/admin/api/activity/clear", json={"scope": "account"})

    assert response.status_code == 400
    assert response.get_json()["status"] == 1
