from pathlib import Path

from netu_app import create_app


STATIC_DIR = Path(__file__).resolve().parents[1] / "netu_app" / "static"


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


def test_index_page_contains_action_feedback_area(tmp_path):
    app = build_app(tmp_path)
    client = app.test_client()
    login_account(client, app)

    response = client.get("/")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'id="actionStatus"' in body
    assert 'id="actionAuthModal"' in body
    assert 'id="inlinePreviewModal"' in body


def test_index_page_hides_recycle_bin_for_regular_users(tmp_path):
    app = build_app(tmp_path)
    client = app.test_client()
    login_account(client, app)

    body = client.get("/").get_data(as_text=True)

    assert 'data-username="alice"' in body
    assert 'id="recycleToggle"' not in body
    assert 'id="recycleList"' not in body
    assert 'id="fileCount"' not in body


def test_admin_page_contains_account_and_file_sections(tmp_path):
    app = build_app(tmp_path)
    client = app.test_client()
    client.post("/login", json={"password": "7bef9fb4b0"})

    body = client.get("/admin").get_data(as_text=True)

    assert 'id="accountList"' in body
    assert 'id="ownerSelect"' in body
    assert 'id="adminFileList"' in body
    assert 'id="adminHiddenList"' in body
    assert 'id="randomLoginBtn"' in body
    assert 'id="sharePanel"' in body
    assert 'id="shareText"' in body
    assert 'id="shareQrLogin"' in body
    assert 'id="shareQrSite"' in body
    assert "qrcode.js" in body


def test_app_js_has_delete_feedback_and_changed_guard():
    content = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

    assert "payload.changed === false" in content
    assert "window.prompt" not in content
    assert "ensureCapabilityAndRun" in content
    assert "openActionModal" in content
    assert "移入回收站" in content
    assert "/api/unlock" in content


def test_admin_js_uses_purge_and_owner_requests():
    content = (STATIC_DIR / "admin.js").read_text(encoding="utf-8")

    assert "/admin/api/accounts" in content
    assert "purge" in content
    assert "owner=" in content


def test_admin_js_generates_symbol_free_random_passwords_and_share_text():
    content = (STATIC_DIR / "admin.js").read_text(encoding="utf-8")

    assert 'RANDOM_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"' in content
    assert "4 + Math.floor(Math.random() * 3)" in content
    assert "navigator.clipboard" in content
    assert "window.location.origin" in content
    assert "sharePanel" in content


def test_admin_js_renders_share_qr_codes():
    content = (STATIC_DIR / "admin.js").read_text(encoding="utf-8")

    assert "window.NetUQR" in content
    assert "NetUQR.draw" in content
    assert "shareQrLogin" in content
    assert "shareQrSite" in content


def test_qrcode_encoder_asset_is_available():
    encoder = STATIC_DIR / "qrcode.js"
    assert encoder.is_file()
    content = encoder.read_text(encoding="utf-8")
    assert "NetUQR" in content
    assert "encode" in content


def test_admin_js_prefills_and_validates_existing_passwords():
    content = (STATIC_DIR / "admin.js").read_text(encoding="utf-8")

    assert "account.login_password" in content
    assert "account.download_password" in content
    assert "account.delete_password" in content
    assert "都不能为空" in content
    assert "owner=all" in content
    assert "file.owner" in content


def test_login_page_has_password_reveal_toggle(tmp_path):
    app = build_app(tmp_path)
    client = app.test_client()

    body = client.get("/login").get_data(as_text=True)

    assert 'id="togglePasswordBtn"' in body
    assert 'name="password"' in body
    assert 'id="loginPassword"' in body


def test_index_page_has_account_note_area(tmp_path):
    app = build_app(tmp_path)
    client = app.test_client()
    login_account(client, app)

    body = client.get("/").get_data(as_text=True)

    assert 'id="accountNote"' in body
    assert "note-input" in body


def test_app_js_autosaves_notes_without_save_button():
    content = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

    assert "/api/account-note" in content
    assert "/api/note" in content
    assert "note-input" in content
    assert "queueNoteSave" in content


def test_admin_js_autosaves_account_and_file_notes():
    content = (STATIC_DIR / "admin.js").read_text(encoding="utf-8")

    assert "/admin/api/note" in content
    assert "data-note-account" in content
    assert "data-note-name" in content
    assert "queueNoteSave" in content


def test_login_page_supports_fragment_quick_login(tmp_path):
    app = build_app(tmp_path)
    client = app.test_client()

    body = client.get("/login").get_data(as_text=True)

    assert "window.location.hash" in body
    assert "replaceState" in body


def test_admin_page_brand_links_home(tmp_path):
    app = build_app(tmp_path)
    client = app.test_client()
    client.post("/login", json={"password": "7bef9fb4b0"})

    body = client.get("/admin").get_data(as_text=True)

    assert 'class="brand" href="/"' in body


def test_index_page_brand_links_home(tmp_path):
    app = build_app(tmp_path)
    client = app.test_client()
    login_account(client, app)

    body = client.get("/").get_data(as_text=True)

    assert 'class="brand" href="/"' in body


def test_login_page_places_mark_and_title_on_one_row(tmp_path):
    app = build_app(tmp_path)
    client = app.test_client()

    body = client.get("/login").get_data(as_text=True)

    assert 'class="auth-head"' in body


def test_hidden_admin_cards_are_collapsed():
    content = (STATIC_DIR / "app.css").read_text(encoding="utf-8")

    assert ".admin-card[hidden]" in content
