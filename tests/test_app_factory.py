from netu_app import create_app
from netu_app.config import load_settings


def test_app_factory_builds(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "NETU_DOWN_DIR": str(tmp_path / "down"),
            "NETU_CONFIG": str(tmp_path / ".passwords.yaml"),
            "NETU_SECRET": "test-secret",
        }
    )
    assert app is not None
    assert app.config["DOWN_DIR"].endswith("down")


def test_load_settings_accepts_host_and_port_overrides():
    settings = load_settings({"NETU_HOST": "127.0.0.1", "NETU_PORT": 5001})

    assert settings["HOST"] == "127.0.0.1"
    assert settings["PORT"] == 5001
