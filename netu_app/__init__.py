from flask import Flask, jsonify

from .auth import AccountManager
from .config import load_settings


def create_app(overrides=None):
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.update(load_settings(overrides or {}))
    app.secret_key = app.config["SECRET_KEY"]
    app.config["PASSWORD_MANAGER"] = AccountManager(
        app.config["PASSWORD_CONFIG_PATH"],
        app.config["SECRET_KEY"],
    )

    from .main_routes import bp as main_bp
    from .admin_routes import bp as admin_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp)

    @app.after_request
    def apply_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        if response.mimetype == "text/html":
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.errorhandler(404)
    def handle_not_found(_error):
        return jsonify({"status": 1, "message": "资源不存在"}), 404

    @app.errorhandler(500)
    def handle_server_error(_error):
        return jsonify({"status": 1, "message": "服务器内部错误"}), 500

    return app
