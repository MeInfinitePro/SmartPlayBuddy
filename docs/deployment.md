# SmartPlayBuddy 部署指南

> 本文档描述整个项目的三层部署：**服务器端（Server）**、**Web 端（前端 + 桥接后端）**、
> **Client 端（设备侧 + 星穹铁道 Mod）**。基于当前代码结构（v0.0.1）整理，不涉及代码改动。

## 1. 架构总览

```
┌────────────────────────────────────────────────────────────────┐
│                     服务器端 Server（已有远程托管）                │
│   https://smtplay.cabyss.cn         统一登录 / 用户认证（JWT）    │
│   wss://smtplay.cabyss.cn/ws        设备连接 / 消息路由 / 房间    │
└───────┬───────────────────────────────┬────────────────────────┘
        │ WebSocket（出站，JWT 鉴权）      │ WebSocket（临时连接，JWT）
        │                               │
┌───────▼───────────────┐    ┌──────────▼─────────────────────────┐
│  Client 端（游戏机）     │    │  Web 端（可单机或部署到服务器）        │
│  smtplay 客户端进程      │    │  web/backend/app.py（FastAPI 桥接） │
│   ├─ DriverRegistry    │    │   ├─ /api/auth/*  统一登录会话       │
│   │   keyboard/mouse/  │    │   ├─ /api/starrail/* 指令转发        │
│   │   screen/starrail  │    │   └─ 静态托管 web/frontend/dist     │
│   └─ mods/starrail     │    └──────────┬─────────────────────────┘
│       （Mod 逻辑编排）   │               │ 浏览器访问（Cookie 会话）
└───────┬───────────────┘    ┌──────────▼──────────┐
        │ 驱动子进程 IPC       │  使用者浏览器         │
        ▼                    └─────────────────────┘
  星穹铁道游戏客户端
```

三个要点：

- **Client 与 Web 后端都是"出站连接"**：主动连服务器 WS，机器上不需要开放任何入站端口，
  这使得它们可以部署在任何 NAT 后面（家庭网络、校园网均可）。
- **服务器端是唯一需要公网可达的组件**，当前已远程托管，无需自行部署。
- **统一登录口径在 Web 后端**：`/api/auth/callback` 唯一回跳，`spb_session` Cookie 全站共享，
  插件前后端均不实现登录逻辑。

## 2. 前置条件

| 组件 | 要求 |
|------|------|
| 服务器端 | 已托管（`smtplay.cabyss.cn`），自建见第 3 节 |
| Client 端 | Windows 10+（截屏驱动依赖 DirectX）、Python ≥ 3.10、星穹铁道国服客户端 |
| Web 端 | Python ≥ 3.10（FastAPI / uvicorn / websockets）、Node.js ≥ 18（仅构建时需要） |
| 账号 | 统一登录（OAuth + PKCE）账号一个 |

## 3. 服务器端部署

### 3.1 使用现有托管（推荐）

服务器端已托管于 `smtplay.cabyss.cn`，Client 与 Web 端通过
`src/smartplaybuddy/config/__init__.py` 中的常量对接：

```python
SERVER_HOST = "https://smtplay.cabyss.cn"
WS_URL = "wss://smtplay.cabyss.cn/ws"
```

无需任何部署动作。

### 3.2 自建服务器端（可选）

需要提供两个服务：

1. **HTTPS 认证服务（443 → 内网 :8000）**：统一登录页、`/api/user/auth/authorize`（返回登录页地址）、
   `/api/user/auth/callback`（回跳并携带 accessToken/refreshToken/expiresIn）、
   `/api/user/auth/refresh`（刷新 token）。
2. **WebSocket 路由服务（443/wss → 内网 :2508）**：JWT 鉴权接入、设备注册（deviceName）、
   房间路由（`mod:{userId}:{modName}`）、文本 + 二进制双帧协议转发。

自建时建议前置 Nginx 统一入口（客户端默认 wss，必须启用 443，完整模板见 `deploy/nginx/smtplay-server.conf`）：

```nginx
server {
    listen 80;
    server_name smtplay.example.cn;
    return 301 https://$host$request_uri;   # HTTP 强制跳 HTTPS
}

server {
    listen 443 ssl;
    http2 on;
    server_name smtplay.example.cn;
    ssl_certificate     /etc/nginx/certs/fullchain.pem;   # 按实际路径
    ssl_certificate_key /etc/nginx/certs/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;
    }

    location /ws {
        proxy_pass http://127.0.0.1:2508;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 3600s;   # WS 长连接不被掐断
    }
}
```

## 4. Web 端部署（前端 + 桥接后端）

### 4.1 构建前端

```bash
cd web/frontend
npm install        # 首次
npm run build      # 产出 dist/，后端静态托管该目录
```

### 4.2 启动桥接后端

```bash
# 项目根目录；--host 0.0.0.0 允许局域网访问，默认 localhost 仅本机
python web/backend/app.py                 # 默认 0.0.0.0:8765 的写法见 main()，显式指定：
python web/backend/app.py --host 0.0.0.0 --port 8765
```

启动后浏览器访问 `http://<部署机IP>:8765`：

1. 首页探测 `/api/auth/me` → 未登录时返回统一登录 `loginUrl`；
2. 点击登录 → OAuth 授权 → 回跳 `/api/auth/callback` 种下 `spb_session`（HttpOnly）；
3. 之后所有 `/api/starrail/*` 接口凭 Cookie 会话调用，token 由后端持有并静默刷新。

> **注意**：`loginUrl` 的回跳地址由实际访问地址生成。局域网分享时使用部署机 IP，
> 不要把 `localhost` 链接发给他人。

### 4.3 部署形态选择

| 形态 | 做法 | 适用 |
|------|------|------|
| 本机自用 | `--host localhost` | 仅自己这台机器访问 |
| 局域网共享 | `--host 0.0.0.0` + 防火墙放行 8765 | 同一局域网（校园网需先测试客户端隔离，见第 7 节） |
| 公网正式服务 | 部署到云服务器 + Nginx + HTTPS | 多人长期使用（推荐最终形态） |

### 4.4 服务器化运行（Linux 云服务器）

```bash
# 进程守护（systemd 示例）
sudo tee /etc/systemd/system/spb-web.service <<'EOF'
[Unit]
Description=SmartPlayBuddy Web Bridge
After=network.target

[Service]
WorkingDirectory=/opt/SmartPlayBuddy
ExecStart=/opt/SmartPlayBuddy/venv/bin/python web/backend/app.py --host 127.0.0.1 --port 8765
Restart=always

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl enable --now spb-web
```

Nginx 收口（对外 443/HTTPS，对内转发 8765，完整模板见 `deploy/nginx/spb-web.conf`）：

```nginx
server {
    listen 80;
    server_name spb.example.cn;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    http2 on;
    server_name spb.example.cn;
    ssl_certificate     /etc/nginx/certs/fullchain.pem;   # 按实际路径
    ssl_certificate_key /etc/nginx/certs/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;   # 网关借此拼出 https 的登录回跳
    }
}
```

> 建议随服务器化一并落地两个加固项：
> ① `SESSIONS` 内存会话表外置（SQLite/Redis），避免重启掉线、支持多进程；
> ② `/api/auth/callback` 支持 `redirect` 参数，登录后回跳原插件页。

## 5. Client 端部署（游戏机）

Client 端 = **SmartPlayBuddy 客户端进程（设备侧）** + **星穹铁道 Mod（业务编排）**。
两者都在游戏所在的 Windows 机器上运行。

### 5.1 安装

```bash
cd SmartPlayBuddy
pip install -e .          # 客户端本体 + 驱动依赖（dxcam / opencv / pyautogui / websockets 等）
```

### 5.2 启动客户端（设备侧）

```bash
smtplay
```

启动流程（自动完成）：

1. 自动登录或打开浏览器完成统一登录（JWT 存入系统 keyring）；
2. 扫描并加载本地驱动（keyboard / mouse / screen / starrail）；
3. 连接服务器 WS，以本机主机名作为 `deviceName` 注册，等待指令。

> Client 全程只发起出站连接，无需配置防火墙入站规则。

### 5.3 启动星穹铁道 Mod（业务侧）

```bash
# 同机部署（client 与 mod 在同一台机器）：缺省取主机名
python -m mods.starrail

# 跨机部署：显式指定目标设备名（client 的 deviceName）
python -m mods.starrail --target-client <deviceName>
```

Mod 启动后加入 `mod:{userId}:starrail` 房间，等待 Web 端（或调试命令）下发的指令。

### 5.4 命令行调试（不经 Web 端直接验证 Mod）

```bash
python -m mods.starrail.controller --operate ping
python -m mods.starrail.controller --operate power/query
```

### 5.5 运行测试（可选，验证安装完整性）

```bash
python -m pytest tests/ -v
```

## 6. 部署验证清单

按顺序执行，每步通过再进行下一步：

| # | 验证项 | 命令 / 操作 | 预期 |
|---|--------|------------|------|
| 1 | Client 连接 | 观察 `smtplay` 日志 | WS 连接成功、驱动加载、deviceName 注册 |
| 2 | Mod 上线 | 观察 `python -m mods.starrail` 日志 | 加入 mod 房间 |
| 3 | Web 登录 | 浏览器打开 `http://<web-ip>:8765` → 去统一登录 | 回跳后展示功能页 |
| 4 | 全链路连通 | 页面点 Ping（或 `POST /api/starrail/ping`） | Mod 级 pong |
| 5 | 驱动连通 | 页面点 Driver Ping | 驱动级 pong（全链路） |
| 6 | 状态查询 | 页面 Status / 体力查询 | 返回体力数据（截屏 + OCR 链路正常） |
| 7 | 长流程 | 清体力（小额度如 10 点） | Job 创建 → 进度事件 → 完成 |

## 7. 网络环境注意事项

- **家庭 / 宿舍路由器**：Web 端部署机在路由器上做 DHCP 静态绑定固定 IP，
  使用者访问 `http://<固定IP>:8765`。
- **校园网**：存在客户端隔离（同网设备互不可达）、IP 不受控、Windows 识别为公用网络
  （默认禁入站）三重问题。不推荐作为承载环境；如必须使用，建议接入
  [Tailscale](https://tailscale.com) 等 WireGuard 组网工具，以虚拟固定 IP 互访。
- **跨网访问 / 正式服务**：Web 端部署到云服务器（第 4.4 节），Client 留在游戏机
  （出站连接不受 NAT 限制），这是最终推荐形态。

## 8. 常见问题

| 现象 | 排查 |
|------|------|
| 页面 404 / 提示未找到前端构建产物 | 未执行 `npm run build`，或 dist 目录不在 `web/frontend/dist` |
| 登录后立即又要求登录 | `SESSIONS` 为进程内存，服务重启即失效；确认服务未被反复拉起 |
| 局域网他人无法打开 | Windows 防火墙入站规则放行 8765；确认网络配置文件（专用/公用） |
| 登录回跳地址是 localhost | 使用者必须用部署机实际 IP/域名访问，回跳地址跟随访问地址生成 |
| Ping 无响应 | Client 未启动 / Mod 未启动 / `--target-client` 与 deviceName 不一致 |
| 启动游戏很慢 | 首次启动需全盘搜索游戏路径，属正常（超时上限 300s） |
| 长操作前端一直转圈 | 轮询 `GET /api/jobs/{jobId}` 查看 events 进度与 error 字段 |
