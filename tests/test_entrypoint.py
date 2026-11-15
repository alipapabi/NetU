import importlib


def test_legacy_entry_exposes_flask_app():
    module = importlib.import_module("file_downloader")

    assert hasattr(module, "app")
    assert module.app is not None
    assert "PASSWORD_MANAGER" in module.app.config
