# 项目结构组织建议（部署方法学视角）

> 本文回答：按软件工程部署方法学，本项目结构应如何组织。
> **仅为目标设计与迁移路径，不改动任何现有文件。**

## 1. 现状诊断（对照部署方法学）

| # | 方法学原则 | 现状 | 差距 |
|---|-----------|------|------|
| 1 | **部署单元可独立交付** | 三处部署单元（Client、WebAPI、WebUI）混在一个目录树里：Client 在 `src/`+`mods/`，WebAPI 在 `web/backend/`，WebUI 在 `web/frontend/` | 边界靠口头约定，无产物定义 |
| 2 | **配置与代码分离**（12-Factor III） | `src/smartplaybuddy/config/__init__.py` 硬编码 `SERVER_HOST` / `WS_URL`，换环境要改源码 | 无环境变量/分层配置 |
| 3 | **依赖声明完整**（12-Factor II） | 根 `requirements.txt`（client 依赖）与 `web/backend/requirements.txt`（webapi 依赖）分裂；webapi 未纳入 `pyproject.toml` 管理 | webapi 无版本化安装方式 |
| 4 | **无状态进程**（12-Factor VI） | WebAPI 的 `SESSIONS` 会话表在进程内存 | 重启掉线、无法水平扩展 |
| 5 | **构建产物不入库** | `web/frontend/dist`、`logs/`、`__pycache__` 散落工作树 | 需确认 `.gitignore` 覆盖完整 |
| 6 | **部署资产版本化** | Nginx/systemd/env 模板等部署知识散落在文档里（如 `docs/deployment.md`） | 无 `deploy/` 目录承载可执行资产 |
| 7 | **遗留代码治理** | `web/frontend-legacy/` 仍在树内 | 增加理解与构建噪音 |

## 2. 目标结构（Monorepo，三个部署单元）

```
SmartPlayBuddy/
├── apps/                              # ★ 部署单元层：每个子目录 = 一份独立交付物
│   ├── client/                        #   设备端（用户本地 Windows，下载分发）
│   │   ├── pyproject.toml             #   独立包：smartplaybuddy-client → 命令 smtplay
│   │   └── ...
│   ├── webapi/                        #   FastAPI 桥接服务（服务器）
│   │   ├── pyproject.toml             #   独立包：smartplaybuddy-webapi
│   │   ├── Dockerfile
│   │   └── ...
│   ├── webui/                         #   Vue 前端（服务器，构建产物随 webapi 发布）
│       ├── package.json / package-lock.json   # lockfile 锁定，保证可重复构建
│       └── ...
│   └── modhost/                       #   Mod 常驻进程（服务器，独立于 webapi）
│       └── pyproject.toml             #   smartplaybuddy-modhost（装载 mods/*）
│
├── packages/                          # ★ 共享库层：被多个 app 依赖，不单独部署
│   └── core/                          #   现 src/smartplaybuddy（协议/ws/user/mod基类/
│       │                              #   驱动框架；drivers/* 随 client 分发）
│       └── pyproject.toml             #   smartplaybuddy-core
│
├── deploy/                            # ★ 部署资产层：环境差异全部收在这里
│   ├── .env.example                   #   环境变量清单（SERVER_HOST / WS_URL / SPB_SESSION_SECRET...）
│   ├── nginx/
│   │   ├── smtplay-server.conf        #   服务器端反代（含 WS Upgrade）
│   │   └── spb-web.conf               #   Web 端反代（X-Forwarded-Proto）
│   ├── systemd/
│   │   ├── spb-web.service
│   │   └── spb-modhost.service
│   └── docker-compose.yml             #   webapi + modhost + redis(会话) + nginx 一键起
│
├── docs/                              # 文档（deployment.md / driver.md / ...）
├── tests/                             # 测试（按单元分子目录，对应 apps/packages）
├── .gitignore                         # dist/ logs/ __pycache__/ .env 等
├── pyproject.toml                     # workspace 根（仅工具配置：pytest/ruff，不重复声明依赖）
└── README.md
```

**部署切分依据**（指令流向决定代码归属）：

```
服务器:   WebUI ─▶ WebAPI ─▶ modhost(mods/* 编排逻辑)
                               │ operate(ep) 经服务器路由
用户本地:  client(DriverRegistry) ─▶ drivers/*（截屏/OCR/键鼠，必须与游戏同机）
```

- `mods/*` 是纯编排逻辑，不接触屏幕与游戏 → 常驻服务器（modhost），**高频迭代、用户无感更新**；
- `drivers/*`（含 starrail 的截屏/OCR/键鼠）必须与游戏同机 → 随 Client 下载分发，**低频发版**；
- Mod 迭代与 Client 分发由此解耦：改任务流程只更新服务器，只有驱动层变更才需重新分发 Client。

### 2.1 补充：Client 内部的易变性切分（资源热更通道）

注意：starrail 驱动中**真正易变的是数据而非代码**——游戏版本更新后，模板截图、
UI 坐标、OCR 阈值、任务入口判定都要跟着改，而识别算法骨架（截图→匹配→点击→校验）
长期稳定。据此在 Client 内部再切一层：

```
apps/client/
├── drivers/starrail/
│   ├── module/...            # 算法骨架：稳定，随 exe/wheel 发版
│   └── assets / 坐标 / 阈值   # 数据层：剥离为外部资源，可热更
packages/core/
└── resource-sync（新增）      # 启动时向服务器核对资源包版本，差量下载 + 哈希校验
deploy/
└── resource-pack/            # 服务器端版本化资源包（模板图/坐标表/阈值 JSON）
```

| 层 | 内容 | 更新方式 | 频率 |
|----|------|---------|------|
| Client exe/wheel | core + 识别算法骨架 | 用户下载新版 | 最低 |
| 资源包 | 模板图/坐标/阈值（应对游戏 UI 变动） | 服务器推送，Client 启动时拉取 | 高，用户无感 |
| Mod / WebAPI / WebUI | 编排与界面 | 服务器直接更新 | 中 |

DriverRegistry 的子进程隔离保证热更安全：资源加载失败时 driver 子进程回退旧版资源，
不拖垮 Client 主进程。落地动作：将 `drivers/starrail/module/` 与 `assets/` 中的
硬编码坐标、模板路径、阈值常量外部化为 JSON/YAML 数据文件 + 一个启动时版本核对函数。

**分层规则**（依赖方向单向）：

```
apps/* ──依赖──▶ packages/* ──依赖──▶ 第三方库
deploy/* ──描述如何运行──▶ apps/*
```

- `apps` 之间互不依赖（client 不知道 webapi 存在），符合"部署单元独立演进"；
- `packages` 只出库不出进程，版本号独立递增；
- 一切"换个环境要改的东西"只允许出现在 `deploy/` 与环境变量中。

## 3. 部署单元与产物矩阵

| 部署单元 | 现有位置 | 目标位置 | 交付产物 | 运行环境 | 触发部署的变更 | 更新频率 |
|---------|---------|---------|---------|---------|--------------|---------|
| Client（设备端，含 drivers） | `src/smartplaybuddy` + `src/.../drivers/*` | `apps/client` + `packages/core` | wheel 或 PyInstaller 单文件 exe | 用户本地 Windows | core、drivers 变更 | 低频（驱动变更才发版） |
| WebAPI（桥接） | `web/backend` | `apps/webapi` | wheel / Docker 镜像 | Linux 服务器 | webapi 或 core 变更 | 中频 |
| WebUI（前端） | `web/frontend` | `apps/webui` | `dist/` 静态文件（由 WebAPI 托管或 Nginx/CDN） | 随 WebAPI | webui 变更 | 中频 |
| Mod（编排逻辑） | `mods/starrail` | `apps/modhost` | wheel / Docker 镜像 | Linux 服务器 | mods/* 变更 | 高频（用户无感） |

要点：**一次构建，多环境部署**——CI 对 main 分支构建出带版本号的产物（如
`smartplaybuddy-webapi-0.1.0-py3-none-any.whl`），测试环境与生产部署同一份产物，
环境差异只通过 `deploy/.env` 注入，禁止在各环境重新构建。

## 4. 配置策略（修复诊断 #2）

配置三层，优先级从低到高：

```
代码内默认值（仅开发环境合理值）→ deploy/.env 文件 → 系统环境变量
```

目标形态用 `pydantic-settings` 收敛（现 `config/__init__.py` 的替换方案）：

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    server_host: str = "http://localhost:8000"     # 默认值仅服务本地开发
    ws_url: str = "ws://localhost:2508/ws"
    session_secret: str = ""                        # 生产必填，无默认

    model_config = {"env_prefix": "SPB_"}           # 环境变量 SPB_SERVER_HOST 等
```

`deploy/.env.example`（入库模板，真实 `.env` 不入库）：

```bash
SPB_SERVER_HOST=http://smtplay.cabyss.cn:8000
SPB_WS_URL=ws://smtplay.cabyss.cn:2508/ws
SPB_SESSION_SECRET=          # WebAPI 会话签名密钥
SPB_SESSION_STORE=memory     # memory | sqlite | redis（目标：生产强制 redis/sqlite）
```

## 5. CI/CD 流水线（按单元触发）

```
push/PR
  ├─ 路径过滤变更单元（packages/core 变更 → 三个单元全部重建）
  ▼
┌─────────┬─────────┬──────────┬─────────┐
│ lint    │ test    │ build    │ release │
│ ruff    │ pytest  │ 前端 build│ wheel/  │
│ eslint  │ (按单元) │ wheel 打包│ 镜像入库 │
└─────────┴─────────┴──────────┴─────────┘
                                    ▼
                        deploy：webapi 拉镜像 + 迁移 + 滚动重启
                                webui 产物随 webapi 镜像或 Nginx 发布
                                client 产物挂 Release 供游戏机下载
```

最小可行版本：一个 GitHub Actions workflow，三条 job 分别构建三个单元，
产物上传 artifact / Release；部署初期可用手动触发（workflow_dispatch）。

### 5.1 Client 交付链路（用户下载）

Client 是唯一需要"到达用户手里"的单元，交付分三步：

**① 打包（CI，Windows runner）**

| 形态 | 工具 | 目标用户 |
|------|------|---------|
| wheel | `python -m build`（apps/client 的 pyproject，入口 `smtplay`） | 会用 Python 的技术用户：`pip install smartplaybuddy-client` |
| 单文件 exe | PyInstaller / Nuitka（内嵌 Python + core + drivers + 资源引导） | 普通用户，免环境安装 |
| 安装包 | Inno Setup / NSIS 包一层 exe（快捷方式、开机自启、卸载） | 正式分发形态 |

打包范围只含 `apps/client` + `packages/core`（含 drivers）+ 初始资源包，
**不含** modhost / webapi / webui——由 monorepo 的单元边界天然保证。

**② 发布（服务器端版本清单）**

CI 产物上传到服务器的静态分发目录，并更新版本清单（WebAPI 提供接口）：

```
GET /api/client/version
→ { "version": "0.1.0", "url": ".../client/0.1.0/setup.exe", "sha256": "...", "minSupported": "0.0.9" }
```

`minSupported` 用于强制升级判断：Client 代码版本低于它时，提示必须重新下载。

**③ 下载与升级（用户侧）**

- **首次获取**：WebUI 提供"下载客户端"页面（读取 version 接口渲染下载按钮），
  或直接发布直链；
- **资源热更**（数据层）：Client 启动时经 `packages/core` 的 resource-sync 模块
  拉取差量资源包，不涉及 exe 更换——高频，用户无感；
- **代码升级**（程序层）：Client 启动时同样查 version 接口，发现新版后提示用户
  下载新 exe（安装包形态可后续演进为后台下载 + 校验替换的自动更新器）。

两条通道合起来：**数据变更走资源热更（不换 exe），代码变更走版本清单引导重装**，
用户手动下载的频率被压到最低。

## 6. 渐进迁移路径（不破坏现状，按序执行）

| 阶段 | 动作 | 影响 |
|------|------|------|
| P0 | 补全 `.gitignore`（dist/logs/__pycache__/.env）；新增 `deploy/.env.example`；归档 `frontend-legacy` | 零风险 |
| P1 | `config/__init__.py` 换为 pydantic-settings 分层读取，默认值保持现值 | 行为不变，配置可注入 |
| P2 | `web/backend` 包化：迁入 `apps/webapi`，补 `pyproject.toml`，依赖合并去重 | WebAPI 可独立版本化 |
| P3 | `src/smartplaybuddy` → `packages/core`，`mods/starrail` → `packages/mod-starrail`，Client 薄壳进 `apps/client`；`git mv` 保留历史 | 一次性结构 PR |
| P4 | 建 `deploy/docker-compose.yml` 与 CI workflow；`SESSIONS` 外置 SQLite/Redis | 具备正式部署能力 |

每阶段独立成 PR，P0–P2 不改任何 import 路径，P3 才动目录，风险可控。

## 7. 与现有文档的关系

- `docs/deployment.md`（部署操作手册）描述"怎么部署"，本文描述"结构为什么这样组织、
  怎么演进"。两者配合：迁移到 P4 后，deployment.md 中"服务器化运行"一节将简化为
  `docker compose up -d` + 注入 `.env`。
