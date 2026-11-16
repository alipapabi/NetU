import hashlib
import shutil
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from flask import (
    Blueprint,
    current_app,
    jsonify,
    render_template,
    request,
    send_file,
)

from .activity import ACTION_LABELS, SUPERADMIN_USERNAME, get_activity_log, log_activity
from .auth import (
    ADMIN_COOKIE,
    DEFAULT_ACCOUNT_EXPIRE_DAYS,
    get_account_manager,
    require_superadmin,
)
from .file_service import FileService
from .preview_service import PreviewService
from .security import is_valid_username, normalize_note

bp = Blueprint("admin", __name__)

ROOT_OWNER = "root"
ALL_OWNERS = "all"


def down_root():
    return Path(current_app.config["DOWN_DIR"])


def resolve_owner_dir(owner):
    """返回某 owner 对应的目录；owner 为空或 'root' 表示公共区（down 根目录）。"""
    if not owner or owner == ROOT_OWNER:
        return down_root()
    if not is_valid_username(owner) or not get_account_manager().get_account(owner):
        return None
    return down_root() / owner


def owner_from_request():
    owner = request.args.get("owner") or (request.get_json(silent=True) or {}).get("owner") or ROOT_OWNER
    return owner


def aggregate_files():
    """汇总公共区与所有账户目录的文件，并在每条记录上标注归属账户。"""
    digest = hashlib.sha256()
    files = []
    hidden = []
    targets = [(ROOT_OWNER, down_root())]
    for account in get_account_manager().list_accounts():
        targets.append((account["username"], down_root() / account["username"]))
    for owner, directory in targets:
        payload = FileService(directory).list_files()
        digest.update(owner.encode("utf-8"))
        digest.update(payload["etag"].encode("utf-8"))
        for item in payload["files"]:
            item["owner"] = owner
            files.append(item)
        for item in payload["hidden"]:
            item["owner"] = owner
            hidden.append(item)
    files.sort(key=lambda item: item.get("modified", 0), reverse=True)
    hidden.sort(key=lambda item: item.get("modified", 0), reverse=True)
    return {"etag": digest.hexdigest(), "files": files, "hidden": hidden}


@bp.get("/admin")
@require_superadmin(page_redirect=True)
def admin_index():
    return render_template(
        "admin.html",
        security=current_app.config["PASSWORD_MANAGER"].get_security_settings(),
        default_expire_days=DEFAULT_ACCOUNT_EXPIRE_DAYS,
    )


@bp.get("/admin/api/accounts")
@require_superadmin()
def list_accounts():
    return jsonify({"status": 0, "accounts": get_account_manager().list_accounts()})


@bp.post("/admin/api/accounts")
@require_superadmin()
def create_account():
    data = request.get_json(silent=True) or {}
    try:
        get_account_manager().create_account(
            data.get("username", ""),
            data.get("login_password", ""),
            data.get("download_password", ""),
            data.get("delete_password", ""),
            enabled=bool(data.get("enabled", True)),
            expire_days=data.get("expire_days"),
        )
    except ValueError as error:
        return jsonify({"status": 1, "message": str(error)}), 400
    return jsonify({"status": 0, "message": "账户已创建"})


@bp.post("/admin/api/accounts/<username>")
@require_superadmin()
def update_account(username):
    data = request.get_json(silent=True) or {}
    enabled = data.get("enabled")
    try:
        get_account_manager().update_account(
            username,
            login_password=data.get("login_password") or None,
            download_password=data.get("download_password") or None,
            delete_password=data.get("delete_password") or None,
            enabled=None if enabled is None else bool(enabled),
            expire_days=data.get("expire_days"),
        )
    except ValueError as error:
        return jsonify({"status": 1, "message": str(error)}), 400
    return jsonify({"status": 0, "message": "账户已更新"})


@bp.post("/admin/api/accounts/<username>/note")
@require_superadmin()
def set_account_note(username):
    data = request.get_json(silent=True) or {}
    try:
        note = get_account_manager().set_account_note(username, data.get("note", ""))
    except ValueError as error:
        return jsonify({"status": 1, "message": str(error)}), 404
    return jsonify({"status": 0, "message": "已保存", "note": note})


@bp.delete("/admin/api/accounts/<username>")
@require_superadmin()
def delete_account(username):
    manager = get_account_manager()
    if not manager.get_account(username):
        return jsonify({"status": 1, "message": "账户不存在"}), 404
    source = down_root() / username
    if source.is_dir():
        trash = down_root() / ".trash"
        trash.mkdir(parents=True, exist_ok=True)
        destination = trash / f"{username}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        shutil.move(str(source), str(destination))
    manager.remove_account(username)
    return jsonify({"status": 0, "message": "账户已删除，文件已移入 .trash"})


@bp.post("/admin/api/security")
@require_superadmin()
def save_security():
    data = request.get_json(silent=True) or {}
    try:
        ttl_days = max(1, int(data.get("cookie_ttl_days", 7)))
    except (TypeError, ValueError):
        return jsonify({"status": 1, "message": "Cookie 有效期必须为正整数"}), 400
    current_app.config["PASSWORD_MANAGER"].update_security(cookie_ttl_days=ttl_days)
    return jsonify({"status": 0, "message": "安全配置已更新"})


@bp.post("/admin/api/superadmin")
@require_superadmin()
def change_superadmin_password():
    data = request.get_json(silent=True) or {}
    password = data.get("password", "")
    if not isinstance(password, str) or len(password) < 4:
        return jsonify({"status": 1, "message": "超级管理员密码至少 4 位"}), 400
    get_account_manager().set_superadmin_password(password)
    response = jsonify({"status": 0, "message": "密码已更新，请重新登录"})
    response.delete_cookie(ADMIN_COOKIE, path="/")
    return response


@bp.get("/admin/api/files")
@require_superadmin()
def admin_files():
    owner = owner_from_request()
    if owner == ALL_OWNERS:
        payload = aggregate_files()
    else:
        directory = resolve_owner_dir(owner)
        if directory is None:
            return jsonify({"status": 1, "message": "账户不存在"}), 404
        payload = FileService(directory).list_files()
        label = owner or ROOT_OWNER
        for group in ("files", "hidden"):
            for item in payload[group]:
                item["owner"] = label
    if request.args.get("since") == payload["etag"]:
        return jsonify({"changed": False, "etag": payload["etag"], "files": [], "hidden": []})
    return jsonify({"changed": True, **payload})


@bp.post("/admin/api/upload")
@require_superadmin()
def admin_upload():
    directory = resolve_owner_dir(owner_from_request())
    if directory is None:
        return jsonify({"status": 1, "message": "账户不存在"}), 404
    if "file" not in request.files:
        return jsonify({"status": 1, "message": "没有文件"}), 400
    service = FileService(directory)
    incoming = request.files["file"]
    filename = service.make_upload_name(incoming.filename or "upload.bin")
    incoming.save(service.base_dir / filename)
    log_activity(SUPERADMIN_USERNAME, "upload", filename)
    return jsonify({"status": 0, "message": "上传成功", "filename": filename})


@bp.post("/admin/api/note")
@require_superadmin()
def admin_note():
    data = request.get_json(silent=True) or {}
    directory = resolve_owner_dir(owner_from_request())
    if directory is None:
        return jsonify({"status": 1, "message": "账户不存在"}), 404
    filename = data.get("filename", "")
    if not FileService(directory).write_note(filename, data.get("note", "")):
        return jsonify({"status": 1, "message": "文件不存在"}), 404
    return jsonify({"status": 0, "message": "已保存"})


@bp.post("/admin/api/delete")
@require_superadmin()
def admin_delete():
    data = request.get_json(silent=True) or {}
    directory = resolve_owner_dir(owner_from_request())
    if directory is None:
        return jsonify({"status": 1, "message": "账户不存在"}), 404
    filename = data.get("filename", "")
    mode = data.get("mode", "hide")
    service = FileService(directory)
    if mode == "purge":
        ok = service.purge(filename)
        message = "已彻底删除"
    else:
        ok = service.hide(filename)
        message = "已隐藏"
    if not ok:
        return jsonify({"status": 1, "message": "文件不存在"}), 404
    log_activity(SUPERADMIN_USERNAME, "delete", filename)
    return jsonify({"status": 0, "message": message})


@bp.post("/admin/api/restore")
@require_superadmin()
def admin_restore():
    data = request.get_json(silent=True) or {}
    directory = resolve_owner_dir(owner_from_request())
    if directory is None:
        return jsonify({"status": 1, "message": "账户不存在"}), 404
    if not FileService(directory).restore(data.get("filename", "")):
        return jsonify({"status": 1, "message": "文件不存在"}), 404
    return jsonify({"status": 0, "message": "已恢复"})


@bp.get("/admin/file/download")
@require_superadmin(page_redirect=True)
def admin_download():
    directory = resolve_owner_dir(request.args.get("owner"))
    if directory is None:
        return jsonify({"status": 1, "message": "账户不存在"}), 404
    target = FileService(directory).resolve_any(request.args.get("filename", ""))
    if target is None:
        return jsonify({"status": 1, "message": "文件不存在"}), 404
    log_activity(SUPERADMIN_USERNAME, "download", request.args.get("filename", ""))
    return send_file(target, as_attachment=True, download_name=target.name)


@bp.get("/admin/file/view")
@require_superadmin(page_redirect=True)
def admin_view():
    owner = request.args.get("owner") or ROOT_OWNER
    directory = resolve_owner_dir(owner)
    if directory is None:
        return jsonify({"status": 1, "message": "账户不存在"}), 404
    filename = request.args.get("filename", "")
    target = FileService(directory).resolve_any(filename)
    if target is None:
        return jsonify({"status": 1, "message": "文件不存在"}), 404

    preview = PreviewService(current_app.config["DOWN_DIR"]).build_view(filename, target)
    quoted_owner = quote(owner)
    quoted_name = quote(filename)
    return render_template(
        "preview.html",
        preview=preview,
        raw_url=f"/admin/file/raw?owner={quoted_owner}&filename={quoted_name}",
        download_url=f"/admin/file/download?owner={quoted_owner}&filename={quoted_name}",
    )


@bp.get("/admin/file/raw")
@require_superadmin(page_redirect=True)
def admin_raw():
    directory = resolve_owner_dir(request.args.get("owner"))
    if directory is None:
        return jsonify({"status": 1, "message": "账户不存在"}), 404
    target = FileService(directory).resolve_any(request.args.get("filename", ""))
    if target is None:
        return jsonify({"status": 1, "message": "文件不存在"}), 404
    return send_file(target, as_attachment=False)


@bp.get("/admin/api/activity")
@require_superadmin()
def admin_activity():
    """返回行为记录，最新的在前；传 username 只看该用户，否则返回全部。"""
    username = (request.args.get("username") or "").strip()
    records = [
        {**item, "action_label": ACTION_LABELS.get(item.get("action"), item.get("action", ""))}
        for item in get_activity_log().list_records(username or None)
    ]
    return jsonify({"status": 0, "username": username, "records": records})


@bp.post("/admin/api/activity/clear")
@require_superadmin()
def admin_activity_clear():
    """清空行为记录：scope=all 清空全部，否则清空 body 中 username 的记录。"""
    data = request.get_json(silent=True) or {}
    log = get_activity_log()
    if data.get("scope") == "all":
        removed = log.clear()
        return jsonify({"status": 0, "message": f"已清空全部记录（{removed} 条）", "removed": removed})
    username = (data.get("username") or "").strip()
    if not username:
        return jsonify({"status": 1, "message": "缺少用户名"}), 400
    removed = log.clear(username)
    return jsonify({"status": 0, "message": f"已清空「{username}」的记录（{removed} 条）", "removed": removed})

