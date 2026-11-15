from pathlib import Path
from urllib.parse import quote

from flask import (
    Blueprint,
    current_app,
    g,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    send_file,
)

from .auth import (
    ABILITY_COOKIES,
    ACCOUNT_ABILITIES,
    ADMIN_COOKIE,
    ALL_COOKIE_NAMES,
    SESSION_COOKIE,
    current_account,
    get_account_manager,
    has_ability,
    is_superadmin,
    require_account_session,
    require_ability,
)
from .file_service import FileService
from .preview_service import PreviewService
from .security import normalize_note

bp = Blueprint("main", __name__)


def account_dir(username):
    return Path(current_app.config["DOWN_DIR"]) / username


@bp.get("/")
def index():
    username = current_account()
    if username:
        return render_template("index.html", username=username)
    if is_superadmin():
        return redirect("/admin")
    return redirect("/login?next=/")


@bp.get("/login")
def login_page():
    return render_template("login.html", next_url=request.args.get("next", "/"))


@bp.post("/login")
def login_submit():
    payload = request.get_json(silent=True) or {}
    is_json_request = request.is_json
    if is_json_request:
        password = payload.get("password", "")
        next_url = payload.get("next") or "/"
    else:
        password = request.form.get("password", "")
        next_url = request.form.get("next") or "/"
    if not isinstance(next_url, str) or not next_url.startswith("/"):
        next_url = "/"

    manager = get_account_manager()
    match = manager.match_login(password)
    if not match:
        if is_json_request:
            return jsonify({"status": 1, "message": "密码错误"}), 401
        return redirect(f"/login?e=1&next={quote(next_url)}")

    ttl_seconds = int(manager.get_security_settings()["cookie_ttl_days"]) * 24 * 60 * 60
    if match["role"] == "superadmin":
        cookie_name = ADMIN_COOKIE
        token = manager.issue_admin_token(ttl_seconds)
        redirect_to = "/admin"
    else:
        cookie_name = SESSION_COOKIE
        token = manager.issue_session_token(match["username"], ttl_seconds)
        redirect_to = "/" if next_url.startswith("/admin") else next_url

    if is_json_request:
        response = make_response(
            jsonify(
                {
                    "status": 0,
                    "message": "验证成功",
                    "role": match["role"],
                    "redirect": redirect_to,
                }
            )
        )
    else:
        response = make_response(redirect(redirect_to))
    for name in ALL_COOKIE_NAMES:
        if name != cookie_name:
            response.delete_cookie(name, path="/")
    response.set_cookie(
        cookie_name,
        token,
        max_age=ttl_seconds,
        httponly=True,
        samesite="Lax",
        path="/",
    )
    # 若登录密码与下载/删除密码相同，则直接签发对应能力，免去二次输入。
    if match["role"] == "account":
        for ability in manager.abilities_matching(match["username"], password):
            response.set_cookie(
                ABILITY_COOKIES[ability],
                manager.issue_ability_token(match["username"], ability, ttl_seconds),
                max_age=ttl_seconds,
                httponly=True,
                samesite="Lax",
                path="/",
            )
    return response


@bp.get("/logout")
def logout():
    response = make_response(redirect("/login"))
    for name in ALL_COOKIE_NAMES:
        response.delete_cookie(name, path="/")
    return response


@bp.get("/api/session")
@require_account_session()
def api_session():
    username = g.account
    account = get_account_manager().get_account(username) or {}
    return jsonify(
        {
            "username": username,
            "note": account.get("note", ""),
            "capabilities": {
                "download": has_ability("download", username),
                "delete": has_ability("delete", username),
            },
        }
    )


@bp.post("/api/account-note")
@require_account_session()
def api_account_note():
    data = request.get_json(silent=True) or {}
    try:
        note = get_account_manager().set_account_note(g.account, data.get("note", ""))
    except ValueError as error:
        return jsonify({"status": 1, "message": str(error)}), 404
    return jsonify({"status": 0, "message": "已保存", "note": note})


@bp.post("/api/note")
@require_account_session()
def api_note():
    data = request.get_json(silent=True) or {}
    filename = data.get("filename", "")
    service = FileService(account_dir(g.account))
    if not service.write_note(filename, data.get("note", "")):
        return jsonify({"status": 1, "message": "文件不存在"}), 404
    return jsonify({"status": 0, "message": "已保存", "note": normalize_note(data.get("note", ""))})


@bp.get("/api/files")
@require_account_session()
def api_files():
    service = FileService(account_dir(g.account))
    payload = service.list_files()
    # 普通用户不展示回收站内容，回收站仅超级管理员可见。
    if request.args.get("since") == payload["etag"]:
        return jsonify({"changed": False, "etag": payload["etag"], "files": []})
    return jsonify(
        {"changed": True, "etag": payload["etag"], "files": payload["files"]}
    )


@bp.post("/api/upload")
@require_account_session()
def api_upload():
    if "file" not in request.files:
        return jsonify({"status": 1, "message": "没有文件"}), 400
    service = FileService(account_dir(g.account))
    incoming = request.files["file"]
    filename = service.make_upload_name(incoming.filename or "upload.bin")
    incoming.save(service.base_dir / filename)
    return jsonify({"status": 0, "message": "上传成功", "filename": filename})


@bp.post("/api/unlock")
@require_account_session()
def api_unlock():
    data = request.get_json(silent=True) or {}
    ability = data.get("ability", "")
    password = data.get("password", "")
    if ability not in ABILITY_COOKIES:
        return jsonify({"status": 1, "message": "无效的操作类型"}), 400
    manager = get_account_manager()
    if not manager.verify_account_ability(g.account, ability, password):
        return jsonify({"status": 1, "message": "密码错误"}), 401
    ttl_seconds = int(manager.get_security_settings()["cookie_ttl_days"]) * 24 * 60 * 60
    token = manager.issue_ability_token(g.account, ability, ttl_seconds)
    response = make_response(jsonify({"status": 0, "message": "验证成功"}))
    response.set_cookie(
        ABILITY_COOKIES[ability],
        token,
        max_age=ttl_seconds,
        httponly=True,
        samesite="Lax",
        path="/",
    )
    return response


@bp.post("/api/delete")
@require_ability("delete")
def api_delete():
    data = request.get_json(silent=True) or {}
    filename = data.get("filename", "")
    service = FileService(account_dir(g.account))
    if not service.hide(filename):
        return jsonify({"status": 1, "message": "文件不存在"}), 404
    return jsonify({"status": 0, "message": "已移入回收站"})


@bp.get("/download/<path:filename>")
@require_account_session(page_redirect=True)
def download_file(filename):
    username = g.account
    if not has_ability("download", username):
        return redirect("/?denied=download")
    service = FileService(account_dir(username))
    target = service.resolve_any(filename)
    if target is None:
        return jsonify({"status": 1, "message": "文件不存在"}), 404
    return send_file(target, as_attachment=True, download_name=target.name)


@bp.get("/preview/<path:filename>")
@require_account_session(page_redirect=True)
def preview_raw(filename):
    service = FileService(account_dir(g.account))
    target = service.resolve_any(filename)
    if target is None:
        return jsonify({"status": 1, "message": "文件不存在"}), 404
    return send_file(target, as_attachment=False)


@bp.get("/view/<path:filename>")
@require_account_session(page_redirect=True)
def view_file(filename):
    service = FileService(account_dir(g.account))
    target = service.resolve_any(filename)
    if target is None:
        return jsonify({"status": 1, "message": "文件不存在"}), 404

    preview = PreviewService(current_app.config["DOWN_DIR"]).build_view(filename, target)
    quoted = quote(filename)
    return render_template(
        "preview.html",
        preview=preview,
        raw_url=f"/preview/{quoted}",
        download_url=f"/download/{quoted}",
    )
