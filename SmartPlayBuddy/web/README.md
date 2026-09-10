# 星穹铁道 Web 前端 + 测试 API

为 SmartPlayBuddy 星穹铁道插件（daily_task / clear_power）提供的 Vue3 前端与 HTTP 测试接口。

## 目录结构

```
web/
├── backend/            FastAPI 桥接服务
│   ├── app.py          认证回调 + starrail REST API + 静态托管（frontend/dist）
│   ├── bridge.py       WS 指令执行器（复用 Message 协议与 controller 模式）
│   └── requirements.txt
├── frontend/           Vue3 + Vite 前端工程（构建产物 dist/ 由后端托管）
│   ├── index.html      Vite 入口
│   ├── vite.config.js  dev 代理 /api → localhost:8765；build → dist/
│   ├── src/
│   │   ├── main.js     应用入口
│   │   ├── App.vue     登录状态机 + 左侧导航壳 + hash 路由（页面 v-show 保活）
│   │   ├── style.css   三月七小助手风格主题（白底 + 左侧导航 + 蓝色按钮，黑色文字）
│   │   ├── api.js      后端 API 封装 + Job 轮询（pollJob）
│   │   ├── log.js      会话级运行日志（全局响应式 store）
│   │   ├── settings.js 目标设备 + 各任务忙碌开关（全局状态）
│   │   ├── powerPlan.js 体力计划 store（设置页编辑、主页实时同步）
│   │   ├── utils.js    fmtTime / fmtErr
│   │   ├── composables/useJobRunner.js  长任务执行器（轮询/进度/日志增量同步）
│   │   ├── components/ DailyCard / PowerCard / ProgressBox
│   │   └── views/      Home / Help / Launch / Log / Settings
│   └── frontend-legacy/  旧版免构建静态前端（存档，不再被托管）
```

## 登录验证（复用已有登录，无登录页）

本前端**不提供登录页面**：

1. 前端加载时请求 `GET /api/auth/me` 探测会话（HTTP-only Cookie）。
2. 未登录时**直接跳转**统一登录页（前端 `location.replace(loginUrl)`，无中间提示页）：

   ```
   {SERVER_HOST}/api/user/auth/authorize?redirectUrl={本服务}/api/auth/callback
   ```

   仅当获取不到登录地址、或登录回跳失败（`?authError=...`）时，才显示错误兜底页
   （带“重新前往统一登录”按钮），避免与统一登录来回死循环。
3. 统一登录回跳 `GET /api/auth/callback?accessToken=...&refreshToken=...&expiresIn=...`
   （契约与客户端本地回调一致），后端建立会话并写 Cookie 后回到首页。
4. access token 过期时后端自动调用 `/api/user/auth/refresh` 静默续期。

## 启动

```bash
# 1) 构建前端（首次需 npm install；Node >= 18）
cd web/frontend
npm install
npm run build          # 产出 dist/，后端托管该目录

# 2) 启动后端（项目根目录；dist 缺失时启动会打印提示）
#    需先安装：pip install fastapi uvicorn websockets
python web/backend/app.py               # 默认 0.0.0.0:8765
python web/backend/app.py --port 9000

# 前端开发模式（热更新，需后端同时在 8765 运行）
cd web/frontend && npm run dev          # http://127.0.0.1:5173，/api 代理到 8765
```

> 注意：将本服务地址（如 `http://<host>:8765/api/auth/callback`）配置为
> 统一登录验证前端验证成功后的跳转 url。

## 前端功能（Vue3 实现，三月七小助手风格：白底 + 左侧导航）

- **主页**：两个功能模块卡片，仅保留两个执行按钮 ——
  - 每日实训：一键「执行完整日常」（观察 → 逐项执行 → 领取奖励）；
  - 清理开拓力：一键「开始清体力」，按「设置 → 体力计划」中的方案执行，卡片实时显示当前计划。
- **设置**：目标设备（deviceName）+ 体力计划（滑杆 0-30、战利品类型 1/2/3、是否使用后备开拓力、
  查询当前/后备开拓力）。
- **日志**：本会话内的任务执行记录（卡片进度实时同步写入）。
- **帮助**：使用说明；**启动游戏**：入口占位（远程启动需客户端侧支持）。
- 任务进度事件与结果 JSON 通过 Job 轮询获得，执行中卡片下方实时刷新。

## 测试 API（要求已登录会话，Cookie 鉴权）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET  | `/api/auth/me` | 会话探测（未登录返回统一登录 url） |
| GET  | `/api/auth/login-url` | 获取统一登录跳转地址 |
| POST | `/api/starrail/ping` | Mod 级连通性检查（同步） |
| POST | `/api/starrail/driver-ping` | 驱动级全链路检查（同步） |
| GET  | `/api/starrail/status` | 驱动状态 + 体力数据（同步） |
| GET  | `/api/starrail/power` | 查询开拓力 current/reserve（同步） |
| GET  | `/api/starrail/daily-task/observe` | 观察未完成实训任务（同步） |
| POST | `/api/starrail/daily-task` | 完整日常，body `{"taskIds":[2,9]}` 可选 → 返回 `jobId` |
| POST | `/api/starrail/daily-task/reward` | 仅领奖 → `jobId` |
| POST | `/api/starrail/clear-power` | 清体力，body `{"powerNum":0-30,"selection":1-3,"useReserve":bool}` → `jobId` |
| POST | `/api/starrail/execute` | 通用指令入口 `{operate, params}` |
| GET  | `/api/starrail/operations` | 指令清单（自描述） |
| POST | `/api/starrail/target-client` | 设置会话默认目标设备名 |
| GET  | `/api/jobs/{jobId}` | 轮询长操作任务（events 进度 + result） |
| POST | `/api/auth/logout` | 退出会话 |

长操作（daily_task / clear_power / reward）立即返回 `{"mode":"job","jobId":...}`，
通过 `GET /api/jobs/{jobId}` 轮询，`status` 为 `running/ok/error`，
`events` 为 Mod 推送的进度事件流。

curl 示例（浏览器登录后带 Cookie）：

```bash
curl -X POST http://localhost:8765/api/starrail/clear-power \
  -H "Content-Type: application/json" \
  -b "spb_session=<session-id>" \
  -d '{"powerNum": 12, "selection": 1, "useReserve": false}'
```
