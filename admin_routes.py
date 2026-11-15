"""
NetU - 管理后台路由模块
- /admin/login          后台登录页
- /admin                后台首页(改密码)
- /admin/api/password   改密码 (POST JSON {pwd_open, pwd_upload, pwd_download, pwd_admin})
- /admin/api/logout     后台登出
"""
from functools import wraps
from flask import request, make_response, redirect, jsonify
import password_store as pwd

# 后台管理自己的 cookie 名
ADMIN_COOKIE = "netu_admin_pwd"


def admin_login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        cookie = request.cookies.get(ADMIN_COOKIE)
        if not cookie or not pwd.verify_cookie("admin", cookie):
            return redirect("/admin/login?next=" + request.path)
        return fn(*args, **kwargs)
    return wrapper


def render_login(mode="admin", next_url="/admin", error="", locked=0):
    """渲染后台登录页(复用同一份登录页 HTML)"""
    err_html = f'<div class="err">{error}</div>' if error else ""
    lock_html = f'<div class="err">🔒 已锁定,剩余 {locked} 秒</div>' if locked else ""
    return f"""<!DOCTYPE html><html lang="zh-CN"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>NetU - 管理后台登录</title>
<style>
body{{font-family:-apple-system,sans-serif;background:#1a1a2e;color:#eee;
display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}}
.box{{background:rgba(255,255,255,.05);padding:32px;border-radius:16px;width:320px;border:1px solid rgba(255,255,255,.12)}}
h1{{margin:0 0 4px;font-size:1.4em}}p{{color:#888;margin:0 0 20px;font-size:.85em}}
input{{width:100%;padding:12px;border:1px solid rgba(255,255,255,.2);border-radius:8px;
background:rgba(0,0,0,.3);color:#fff;font-size:.95em;outline:none;margin-bottom:12px;letter-spacing:2px}}
input:focus{{border-color:#667eea}}
button{{width:100%;padding:12px;background:linear-gradient(135deg,#667eea,#764ba2);
color:#fff;border:none;border-radius:8px;font-size:.95em;cursor:pointer}}
button:hover{{transform:scale(1.02)}}
.err{{background:rgba(255,80,80,.15);color:#ff8888;padding:10px;border-radius:8px;
margin-bottom:12px;font-size:.85em;text-align:center}}
a{{color:#667eea;text-decoration:none;font-size:.85em;display:block;text-align:center;margin-top:14px}}
</style></head><body>
<form class="box" method="post" action="/admin/login">
<h1>🔒 管理后台</h1><p>输入管理密码登录</p>
{err_html}{lock_html}
<input type="password" name="password" placeholder="管理密码" autofocus required>
<input type="hidden" name="next" value="{next_url}">
<input type="hidden" name="mode" value="admin">
<button type="submit">登录</button>
<a href="/">← 返回主页</a>
</form></body></html>"""


def render_admin_page():
    """渲染后台首页(改密码 UI)"""
    cur = pwd.get_all_modes_info()
    return f"""<!DOCTYPE html><html lang="zh-CN"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>NetU - 管理后台</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,sans-serif;background:linear-gradient(135deg,#1a1a2e,#16213e);
min-height:100vh;color:#eee;padding:30px 20px}}
.c{{max-width:720px;margin:0 auto}}
h1{{font-size:1.8em;margin-bottom:6px}}.sub{{color:#888;margin-bottom:30px;font-size:.9em}}
.card{{background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.12);
border-radius:16px;padding:24px;margin-bottom:18px}}
.card h3{{font-size:1.05em;margin-bottom:14px;display:flex;justify-content:space-between}}
.row{{display:flex;gap:10px;align-items:center;margin-bottom:10px}}
.row label{{width:90px;color:#aaa;font-size:.9em}}
.row input{{flex:1;padding:10px 14px;border:1px solid rgba(255,255,255,.2);
border-radius:8px;background:rgba(0,0,0,.25);color:#fff;font-size:.95em;outline:none;letter-spacing:2px}}
.row input:focus{{border-color:#667eea}}
.btn{{padding:10px 20px;background:linear-gradient(135deg,#667eea,#764ba2);
color:#fff;border:none;border-radius:8px;cursor:pointer;font-size:.9em}}
.btn:hover{{transform:scale(1.03)}}.btn-sm{{padding:6px 12px;font-size:.8em}}
.btn-danger{{background:rgba(255,80,80,.2);color:#ff8888;border:1px solid rgba(255,80,80,.3)}}
.toast{{position:fixed;bottom:30px;left:50%;transform:translateX(-50%) translateY(100px);
background:rgba(0,0,0,.9);color:#fff;padding:12px 24px;border-radius:24px;font-size:.9em;
opacity:0;transition:.3s;z-index:9999}}.toast.show{{opacity:1;transform:translateX(-50%) translateY(0)}}
.toast.success{{background:rgba(80,200,120,.9)}}.toast.error{{background:rgba(255,80,80,.9)}}
.actions{{display:flex;gap:8px;justify-content:flex-end;margin-top:8px}}
.logout{{float:right;color:#888;text-decoration:none;font-size:.85em}}.logout:hover{{color:#ff8888}}
code{{background:rgba(255,255,255,.08);padding:2px 6px;border-radius:4px;font-size:.88em;color:#aab}}
table{{width:100%;border-collapse:collapse;margin-top:8px}}
td{{padding:8px 0;border-bottom:1px solid rgba(255,255,255,.06);font-size:.9em}}
td:first-child{{color:#888;width:40%}}td:last-child{{color:#fff}}
</style></head><body><div class="c">
<a class="logout" href="/admin/api/logout">🚪 登出</a>
<h1>🔒 NetU 管理后台</h1>
<p class="sub">在这里修改所有密码 · 改完立即生效 · 旧客户端 cookie 自动失效</p>

<div class="card">
<h3>🔑 修改密码</h3>
<p style="color:#888;font-size:.85em;margin-bottom:14px">留空 = 不修改该密码 · 密码至少 4 位</p>
<div class="row"><label>打开密码</label><input type="password" id="pwd-open" placeholder="访问页面密码"></div>
<div class="row"><label>上传密码</label><input type="password" id="pwd-upload" placeholder="上传文件密码"></div>
<div class="row"><label>下载密码</label><input type="password" id="pwd-download" placeholder="下载文件密码"></div>
<div class="row"><label>管理密码</label><input type="password" id="pwd-admin" placeholder="后台登录密码"></div>
<div class="actions"><button class="btn" onclick="savePwd()">💾 保存修改</button></div>
</div>

<div class="card">
<h3>📋 当前状态</h3>
<table>
<tr><td>文件路径</td><td><code>/home/minux/WEB/downcent/.passwords.yaml</code></td></tr>
<tr><td>上次修改</td><td><code>{cur['mtime']}</code></td></tr>
<tr><td>当前 cookie 名</td><td><code>netu_open_pwd / netu_up_pwd / netu_down_pwd / netu_admin_pwd</code></td></tr>
<tr><td>cookie 有效期</td><td>1 周 (604800 秒)</td></tr>
</table>
</div>
</div>
<div class="toast" id="t"></div>
<script>
function toast(msg,ok){{const t=document.getElementById('t');t.textContent=msg;
t.className='toast show '+(ok?'success':'error');setTimeout(()=>t.className='toast',2500)}}
async function savePwd(){{
  const data={{}};
  for(const k of ['open','upload','download','admin']){{
    const v=document.getElementById('pwd-'+k).value.trim();
    if(v){{if(v.length<4){{toast('密码至少 4 位 ('+k+')',false);return}}data['pwd_'+k]=v}}
  }}
  if(Object.keys(data).length===0){{toast('请至少填写一个密码',false);return}}
  try{{
    const r=await fetch('/admin/api/password',{{method:'POST',headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify(data)}});
    const j=await r.json();
    if(j.ok){{toast('✅ 已保存,旧 cookie 已失效',true);
      ['open','upload','download','admin'].forEach(k=>document.getElementById('pwd-'+k).value='')}}
    else toast('❌ '+j.error,false)
  }}catch(e){{toast('❌ 网络错误',false)}}
}}
</script></body></html>"""


def register_admin_routes(app):
    """注册后台路由到 Flask app"""

    @app.route("/admin/login", methods=["GET", "POST"])
    def admin_login():
        if request.method == "GET":
            err = ""
            if request.args.get("e"):
                err = "❌ 密码错误"
            return render_login("admin", request.args.get("next", "/admin"), err)
        # POST
        pwd_input = request.form.get("password", "")
        next_url = request.form.get("next", "/admin")
        ip = request.remote_addr or "unknown"
        if pwd.is_locked(ip):
            remaining = pwd.get_lock_remaining(ip)
            return render_login("admin", next_url, "", remaining)
        if pwd.verify("admin", pwd_input):
            pwd.reset_failures(ip)
            cookie_val = pwd.make_cookie("admin")
            resp = make_response(redirect(next_url))
            resp.set_cookie(ADMIN_COOKIE, cookie_val, max_age=604800, httponly=True,
                            path="/", samesite="Lax")
            return resp
        else:
            pwd.record_failure(ip)
            return redirect("/admin/login?e=1&next=" + next_url)

    @app.route("/admin")
    @admin_login_required
    def admin_index():
        resp = make_response(render_admin_page())
        # 防缓存,改完密码刷新看到最新状态
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.route("/admin/api/password", methods=["POST"])
    @admin_login_required
    def admin_save_password():
        try:
            data = request.get_json(force=True, silent=False) or {}
        except Exception:
            return jsonify(ok=False, error="JSON 解析失败"), 400
        result = {}
        for k in ["open", "upload", "download", "admin"]:
            v = data.get("pwd_" + k)
            if v:
                if len(v) < 4:
                    return jsonify(ok=False, error=f"{k} 密码至少 4 位"), 400
                result[k] = v
        if not result:
            return jsonify(ok=False, error="没有要修改的密码"), 400
        for mode, new_pwd in result.items():
            pwd.store.set(mode, new_pwd)
        return jsonify(ok=True, changed=list(result.keys()))

    @app.route("/admin/api/logout")
    def admin_logout():
        resp = make_response(redirect("/admin/login"))
        resp.delete_cookie(ADMIN_COOKIE, path="/")
        return resp