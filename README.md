# NetU · 网络U盘

> 一个轻量的自建文件管理与分享服务 —— 多账号隔离、三密码分级、在线预览、零数据库。

NetU 把一台普通 VPS 变成一个私有网盘：每个账号有独立目录，登录 / 下载 / 删除三种操作各有独立密码，管理员在后台统一管理账号和公共文件。全部数据就是磁盘上的文件 + 一个 YAML 配置文件，没有数据库，没有外部依赖。

---

## 特性

### 账号侧

| 功能 | 说明 |
|---|---|
| **独立空间** | 每个账号只能看到 `down/<账号名>/` 下的文件，互不可见 |
| **上传** | 支持拖拽 / 多选，带实时进度条 |
| **下载** | 需先输入**下载密码**解锁（限时） |
| **删除** | 需先输入**删除密码**；删除进回收站，可在后台恢复 |
| **在线预览** | 图片、音频、视频、PDF、Word、Excel、HTML、Markdown、纯文本、代码等 12 类格式直接浏览器打开 |
| **文件备注** | 每个文件可加自己的备注，只自己可见 |
| **账号有效期** | 管理员可设置 30 天 / 90 天 / 永久 |

### 管理侧（超级管理员）

- 账号管理：创建 / 修改 / 停用 / 删除，三类密码可单独重置
- **文件归属分配**：把公共区的文件分配给指定账号，账号登录后立刻可见
- 公共文件管理：上传、预览、下载、删除、从回收站恢复
- 安全策略：登录 Cookie 有效期、连续失败锁定秒数、最大尝试次数
- 超管密码修改（改完所有旧 Cookie 立即失效）

### 安全设计

- **PBKDF2-SHA256 + 240000 轮** 加盐哈希，密码不落明文（除管理员可在后台查看的辅助字段）
- **三种能力独立授权**：登录 ≠ 下载 ≠ 删除，每个动作单独校验，避免一个密码泄露后权限全开
- **Cookie 用 HMAC 签名**：改密码后旧 Cookie 自动失效，不需要手动登出
- `HttpOnly` + `SameSite=Lax`，防 XSS 窃取和 CSRF
- **防暴力破解**：单 IP 连续失败达阈值后锁定 N 秒
- 路径穿越防护（`is_valid_username` + `resolve_visible`）
- 安全响应头：`X-Content-Type-Options: nosniff`、`Referrer-Policy: same-origin`

---

## 快速开始

### 环境要求

- Python **3.10+**（开发测试于 3.12）
- 依赖：`flask`、`pyyaml`

### 1. 获取代码

```bash
git clone https://github.com/<你的用户名>/NetU.git
cd NetU
```

### 2. 安装依赖

```bash
# 方式 A：虚拟环境（推荐）
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 方式 B：系统 Python（Debian/Ubuntu 可能需要 --break-system-packages）
pip install -r requirements.txt
```

> 如果系统里的 `blinker` 等包是 apt 装的、pip 无法升级，用指定目录隔离安装：
> ```bash
> pip install --target /opt/netu/libs flask
> export PYTHONPATH=/opt/netu/libs
> ```

### 3. 启动

```bash
python3 app.py
```

默认监听 `0.0.0.0:8899`，浏览器打开 <http://localhost:8899>。

### 4. 首次登录

首次启动会自动生成 `.passwords.yaml`，**超级管理员默认密码是 `7bef9fb4b0`**。

> ⚠️ **第一件事就是改掉它** —— 登录 `/admin` 后在「超管密码」里修改，或直接编辑配置文件后删除重建。

创建第一个账号：进入 `/admin` → 新建账号 → 填用户名 + 登录密码 + 下载密码 + 删除密码（四选一必填三）。

---

## 生产部署

### 方式一：systemd（推荐，无容器）

```bash
# 1. 放置代码
sudo mkdir -p /opt/netu
sudo cp -r . /opt/netu/downcent
cd /opt/netu/downcent

# 2. 依赖（隔离安装，不污染系统 Python）
sudo pip install --target /opt/netu/libs flask --break-system-packages

# 3. 生成固定密钥（重启不掉登录）
sudo sh -c 'openssl rand -hex 32 > /opt/netu/secret'
sudo sh -c 'printf "NETU_SECRET=%s\n" "$(cat /opt/netu/secret)" > /opt/netu/secret.env'
sudo chmod 600 /opt/netu/secret.env

# 4. 写服务
sudo tee /etc/systemd/system/netu.service > /dev/null <<'EOF'
[Unit]
Description=NetU file service (port 8899)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/netu/downcent
Environment=PYTHONPATH=/opt/netu/libs
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=/opt/netu/secret.env
ExecStart=/usr/bin/python3 /opt/netu/downcent/app.py
Restart=on-failure
RestartSec=10
StandardOutput=append:/var/log/netu.log
StandardError=append:/var/log/netu.log

[Install]
WantedBy=multi-user.target
EOF

# 5. 启动
sudo systemctl daemon-reload
sudo systemctl enable --now netu

# 6. 验证
systemctl status netu --no-pager
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8899/login   # 期望 200
```

### 方式二：Docker

```bash
docker build -t netu .
docker run -d --name netu \
  -p 8899:8899 \
  -e NETU_SECRET="$(openssl rand -hex 32)" \
  -v /srv/netu/down:/app/down \
  -v /srv/netu/config:/app/config \
  netu
```

### 方式三：Nginx + HTTPS 反代（公网建议）

```nginx
server {
    listen 443 ssl http2;
    server_name netu.example.com;

    ssl_certificate     /etc/letsencrypt/live/netu.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/netu.example.com/privkey.pem;

    client_max_body_size 2048m;   # 与 NetU 的上传上限保持一致或更大

    location / {
        proxy_pass http://127.0.0.1:8899;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_request_buffering off;   # 大文件上传不要缓冲到磁盘
        proxy_read_timeout 300s;
    }
}
```

---

## 配置

所有配置通过环境变量覆盖，**全部可选**，不设则用默认值。

| 变量 | 默认值 | 说明 |
|---|---|---|
| `NETU_HOST` | `0.0.0.0` | 监听地址。仅本机反代可设 `127.0.0.1` |
| `NETU_PORT` | `8899` | 监听端口 |
| `NETU_DOWN_DIR` | `<项目>/down` | 文件存储根目录 |
| `NETU_CONFIG` | `<项目>/.passwords.yaml` | 账号与安全配置存放路径 |
| `NETU_SECRET` | `netu-dev-secret` | Cookie 签名密钥。**生产必须改**，改了所有人的登录会失效一次 |

### 关于 `NETU_SECRET`

- 它是 Cookie 的签署密钥。**换了它 = 所有人被登出**（正常行为，不是 bug）
- 不设则用内置默认值 —— 攻击者知道默认值就能伪造 Cookie，**公网部署务必设置成随机值**
- systemd 部署时建议放在独立 `EnvironmentFile`（权限 600），不要写在命令行里

---

## 目录结构

```
NetU/
├── app.py                  # 入口，create_app() + app.run()
├── netu_app/
│   ├── __init__.py         # Flask 应用工厂、蓝图注册、安全响应头、错误处理
│   ├── config.py           # 环境变量 → 配置字典
│   ├── auth.py             # 账号管理、PBKDF2 哈希、过期、防爆破
│   ├── main_routes.py      # 账号侧路由：登录 / 列表 / 上传 / 下载 / 预览 / 删除
│   ├── admin_routes.py     # 超管路由：账号、安全、公共文件、回收站
│   ├── file_service.py     # 文件操作：列举 / 备注 / 重名处理 / 回收站
│   ├── security.py         # 用户名合法性、路径穿越防护
│   ├── preview_service.py  # 12 类格式的在线预览渲染
│   ├── static/             # 前端 JS / CSS
│   └── templates/          # 登录页 / 文件管理器 / 管理后台 / 预览页
├── down/                   # 🔒 文件存储（首次运行自动创建，不进版本库）
├── .passwords.yaml         # 🔒 账号与密码（首次运行自动生成，不进版本库）
├── requirements.txt
└── .gitignore
```

### 存储布局

```
down/                      ← 公共区（未分配给具体账号的文件，只有超管能看）
├── 一些公共文件.pdf
├── SXRM/                  ← 账号 SXRM 的私有目录
│   └── 资料.docx
└── XZ/
    └── ...
```

账号登录后只看得到 `down/<自己的用户名>/`。超管可在后台把公共区的文件「分配」给任意账号。

---

## 主要 API

所有接口返回 JSON，`status: 0` 表示成功。

### 账号侧

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/login` | 登录，body `{"password": "..."}` |
| `GET` | `/logout` | 登出 |
| `GET` | `/api/session` | 当前会话信息 |
| `GET` | `/api/files` | 文件列表 |
| `POST` | `/api/upload` | 上传（multipart，字段名 `file`） |
| `POST` | `/api/unlock` | 解锁能力，body `{"ability": "download"/"delete", "password": "..."}` |
| `POST` | `/api/delete` | 删除（需先解锁 delete），body `{"filename": "..."}` |
| `GET` | `/download/<filename>` | 下载 |
| `GET` | `/view/<filename>` | 在线预览 |
| `POST` | `/api/note` | 给文件加备注 |

### 管理侧

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/admin` | 管理后台页面 |
| `GET` | `/admin/api/accounts` | 账号列表 |
| `POST` | `/admin/api/accounts` | 新建账号 |
| `POST` | `/admin/api/accounts/<user>` | 修改账号 |
| `DELETE` | `/admin/api/accounts/<user>` | 删除账号（文件移入 `.trash/`） |
| `POST` | `/admin/api/security` | 安全策略 |
| `POST` | `/admin/api/superadmin` | 修改超管密码 |
| `GET` | `/admin/api/files` | 公共区文件列表 |
| `POST` | `/admin/api/restore` | 从回收站恢复 |

> 新建账号时四个参数至少填三个密码：`username` / `login_password` / `download_password` / `delete_password`，少一个会返回 400。

---

## 安全建议

1. **立刻改默认超管密码** `7bef9fb4b0`
2. **生产必须设置 `NETU_SECRET`** 为随机值，否则 Cookie 可被伪造
3. 公网使用请套 **Nginx + HTTPS**，不要直接裸 HTTP 暴露
4. `.passwords.yaml` 权限设为 `600`，且**永远不要提交到 Git**
5. 定期检查账号有效期，及时停用不再使用的账号
6. 大流量场景建议前置反向代理做限流（NetU 自带的是登录防爆破，不含带宽限速）

---

## 技术栈

- **后端**：Python 3.10+ / Flask
- **存储**：文件系统 + YAML（无数据库）
- **前端**：原生 JavaScript + CSS（无构建步骤，无框架）
- **密码学**：`hashlib.pbkdf2_hmac` + `hmac.compare_digest`

---

## 为什么不用对象存储 / 数据库

场景是「一台小 VPS，几个熟人互相传文件」。引入数据库和对象存储会让部署从「三条命令」变成「一堆依赖」。文件系统天然支持流式下载、断点、预览，YAML 配置文件肉眼可读、可直接改、可随时备份。规模不大时这是最简单可靠的方案。

---

## License

MIT
