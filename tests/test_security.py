from io import BytesIO

from netu_app import create_app
from netu_app.security import MAX_NOTE_LENGTH, normalize_note


def build_app(tmp_path):
    return create_app(
        {
            "TESTING": True,
            "NETU_DOWN_DIR": str(tmp_path / "down"),
            "NETU_CONFIG": str(tmp_path / ".passwords.yaml"),
            "NETU_SECRET": "secret-key",
        }
    )


def login_account(client, app, username="alice"):
    app.config["PASSWORD_MANAGER"].create_account(username, "alice-login", "alice-dl", "alice-del")
    return client.post("/login", json={"password": "alice-login"})


def test_preview_response_sets_nosniff_header(tmp_path):
    app = build_app(tmp_path)
    client = app.test_client()
    login_account(client, app)
    client.post(
        "/api/upload",
        data={"file": (BytesIO(b"hello"), "demo.txt")},
        content_type="multipart/form-data",
    )

    response = client.get("/preview/demo.txt")

    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_login_page_disables_caching(tmp_path):
    app = build_app(tmp_path)
    client = app.test_client()

    response = client.get("/login")

    assert response.status_code == 200
    assert "no-store" in response.headers["Cache-Control"]


def test_unknown_path_returns_json_error(tmp_path):
    app = build_app(tmp_path)
    client = app.test_client()

    response = client.get("/no-such-path")

    assert response.status_code == 404
    assert response.get_json()["status"] == 1


def test_normalize_note_keeps_text_and_strips_control_chars():
    assert normalize_note("  hello\x00world  ") == "helloworld"
    assert normalize_note("第一行\n第二行") == "第一行\n第二行"
    assert normalize_note(None) == ""
    assert normalize_note("x" * (MAX_NOTE_LENGTH + 100)) == "x" * MAX_NOTE_LENGTH
