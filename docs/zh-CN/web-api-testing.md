# 星穹铁道 Web API 测试指南

针对 `web/backend/app.py` 提供的 REST API（每日实训 daily_task / 清体力 clear_power）
的完整测试指南。所有接口均为 **Cookie 会话鉴权**（HTTP-only Cookie `spb_session`），
无 Header Token。前端为纯 HTML/JS（`web/frontend`），免构建，后端直接托管。

> 交互式文档：服务启动后可直接访问 **`http://localhost:8765/docs`**（FastAPI 自带
> Swagger UI），可在网页上直接填参调试；`/redoc` 为只读文档版。

---

## 1. 环境准备

### 1.1 启动被测服务

```bash
# 前端为纯 HTML/JS（web/frontend），免构建，直接启动后端即可
python web/backend/app.py --port 8765
```

### 1.1a 自动化接口测试（推荐先跑，无需登录与游戏链路）

```bash
python -m pytest tests/test_web_backend.py -v
# 覆盖：静态托管、认证回跳/退出、参数校验(422/400/401)、
# daily_task 与 clear_power 的 params 组装（mock bridge）、Job 轮询
```

### 1.2 启动游戏链路（联调/真机测试需要）

| 角色 | 启动方式 | 说明 |
| --- | --- | --- |
| Client | SmartBuddy 客户端在线 | 提供截屏与输入控制 |
| starrail Mod | `python -m mods.starrail --target-client <设备名>` | 执行游戏操作 |
| 游戏前置 | 1920×1080 窗口化前台、简体中文 | 图像识别前提 |

仅做 **接口层测试**（验证鉴权、参数校验、错误码）无需游戏链路，
但所有 starrail 指令会因 Mod 离线返回 502/timeout。

---

## 2. 获取测试会话（关键前置）

所有 `/api/starrail/*` 与 `/api/jobs/*` 接口要求已登录会话。三种获取方式：

### 方式 A：浏览器登录 + 复制 Cookie（最简单）

1. 浏览器打开 `http://localhost:8765` → 点击"前往统一登录验证"完成登录；
2. F12 → 应用/Application → Cookies → 复制 `spb_session` 的值；
3. curl 带 `-b "spb_session=<值>"` 即可。

### 方式 B：纯 curl（适合 CI / 脚本）

```bash
BASE=http://localhost:8765

# ① 拿统一登录页地址（每次调用生成新 nonce）
curl -s "$BASE/api/auth/login-url"
# → {"ok":true,"loginUrl":"https://account.cabyss.cn/oauth/authorize?..."}

# ② 在浏览器打开 loginUrl 登录；登录成功后浏览器会跳到
#    http://localhost:8765/api/auth/callback?accessToken=...&refreshToken=...&expiresIn=...
#    从地址栏复制三个参数值

# ③ 用抓到的 token 建立会话，Cookie 存入本地 jar
curl -s -c cookie.txt "$BASE/api/auth/callback?accessToken=<AT>&refreshToken=<RT>&expiresIn=86400" \
  -o /dev/null -L

# ④ 验证
curl -s -b cookie.txt "$BASE/api/auth/me"
# → {"authenticated":true,"userId":"...","expiresAt":...,"targetClient":null}
```

### 方式 C：Postman / Apifox

先 `GET /api/auth/callback?accessToken=...` 一次（Postman 自动保存 Set-Cookie），
后续请求同 Collection 内自动携带。

---

## 3. 推荐测试顺序（无副作用 → 有副作用）

按风险递增执行，前一步通过再进入下一步：

```
第0步 鉴权       第1步 自描述      第2步 连通性         第3步 只读查询        第4步 长操作(有副作用)
/api/auth/me  →  /api/starrail  →  ping            →  /status          →  clear-power (小规模)
  (未登录401)     /operations       driver-ping        /power               daily-task/reward
                                    (Mod 在线)         daily-task/observe   daily-task
```

### 第 0 步：鉴权

```bash
# 未登录（不带 Cookie）→ 401
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8765/api/starrail/operations
# → 401

# 已登录（方式A/B的 Cookie）→ 200
curl -s -b cookie.txt http://localhost:8765/api/auth/me
# → {"authenticated":true,"userId":"10001","expiresAt":1787...,"targetClient":null}
```

### 第 1 步：接口自描述

```bash
curl -s -b cookie.txt http://localhost:8765/api/starrail/operations
# → {"operates":[...],"syncOperates":[...],"jobOperates":["clear_power","daily_task","daily_task/reward"],"docs":{...}}
```

### 第 2 步：连通性（同步接口）

```bash
# Mod 级：验证 Mod:{uid}:starrail 在线
curl -s -b cookie.txt -X POST http://localhost:8765/api/starrail/ping
# → {"mode":"sync","result":{...}}          Mod 离线 → 502

# 驱动级：全链路（Web → WS → Mod → driver → client）
curl -s -b cookie.txt -X POST http://localhost:8765/api/starrail/driver-ping
```

### 第 3 步：只读查询（同步接口，无游戏副作用）

```bash
# 驱动状态 + 体力数据
curl -s -b cookie.txt http://localhost:8765/api/starrail/status

# 查询开拓力
curl -s -b cookie.txt http://localhost:8765/api/starrail/power
# → {"mode":"sync","result":{"current_power":...,"reserve_power":...}}

# 观察未完成的每日实训任务（返回任务 id 列表，用于下一步勾选）
curl -s -b cookie.txt http://localhost:8765/api/starrail/daily-task/observe
```

### 第 4 步：长操作（有游戏副作用，先小规模）

长操作立即返回 `{"mode":"job","jobId":"..."}`，用 `GET /api/jobs/{jobId}` 轮询。

```bash
# 4.1 清体力 —— 首次测试用最小规模：powerNum=1（清 1×10 点）、类型 1（信用点）
curl -s -b cookie.txt -X POST http://localhost:8765/api/starrail/clear-power \
  -H "Content-Type: application/json" \
  -d '{"powerNum": 1, "selection": 1, "useReserve": false}'
# → {"mode":"job","jobId":"xxxxxxxx"}

# 轮询（status: running → ok/error；events 为 Mod 推送的进度事件流）
curl -s -b cookie.txt http://localhost:8765/api/jobs/<jobId>
# → {"id":"...","status":"running","events":[{"flow":"clear_power","step":...,"detail":...,"ts":...}],"result":null}

# 4.2 仅领取实训奖励
curl -s -b cookie.txt -X POST http://localhost:8765/api/starrail/daily-task/reward

# 4.3 完整日常（观察 → 逐项执行 → 领奖）；也可只执行指定任务
curl -s -b cookie.txt -X POST http://localhost:8765/api/starrail/daily-task \
  -H "Content-Type: application/json" -d '{}'                       # 全部
curl -s -b cookie.txt -X POST http://localhost:8765/api/starrail/daily-task \
  -H "Content-Type: application/json" -d '{"taskIds":[2,9,10]}'     # 指定任务
```

轮询循环脚本（bash）：

```bash
JOB_ID=<上一步返回的 jobId>
while :; do
  S=$(curl -s -b cookie.txt http://localhost:8765/api/jobs/$JOB_ID)
  echo "$S" | head -c 300; echo
  echo "$S" | grep -q '"status":"running"' || break
  sleep 3
done
```

---

## 4. 参数校验用例（不需要游戏链路）

```bash
# powerNum 超范围 → 422（前端限定 0-30，0=全部清完，N=N×10 点开拓力）
curl -s -b cookie.txt -X POST http://localhost:8765/api/starrail/clear-power \
  -H "Content-Type: application/json" -d '{"powerNum": 31}'
# → 422 {"detail":[...powerNum...less_than_equal 30...]}

curl -s -b cookie.txt -X POST http://localhost:8765/api/starrail/clear-power \
  -H "Content-Type: application/json" -d '{"powerNum": -1}'        # → 422

# selection 非法 → 422（1=信用点 2=角色经验 3=光锥经验）
curl -s -b cookie.txt -X POST http://localhost:8765/api/starrail/clear-power \
  -H "Content-Type: application/json" -d '{"powerNum":1,"selection":5}'   # → 422

# 未知 job → 404
curl -s -b cookie.txt http://localhost:8765/api/jobs/not-exist     # → 404

# 未知 operate → 400
curl -s -b cookie.txt -X POST http://localhost:8765/api/starrail/execute \
  -H "Content-Type: application/json" -d '{"operate":"nope"}'      # → 400

# 回跳缺 token → 重定向到首页并带 authError 参数
curl -s -o /dev/null -w "%{http_code} %{redirect_url}\n" \
  "http://localhost:8765/api/auth/callback"                        # → 307 /?authError=missing_token
```

---

## 5. 接口速查表

| 方法 | 路径 | 类型 | 说明 |
| --- | --- | --- | --- |
| GET  | `/api/auth/me` | 认证 | 会话探测（未登录返回 loginUrl） |
| GET  | `/api/auth/login-url` | 认证 | 统一登录跳转地址（每次新 nonce） |
| GET  | `/api/auth/callback` | 认证 | 登录回跳（accessToken/refreshToken/expiresIn） |
| POST | `/api/auth/logout` | 认证 | 退出会话 |
| GET  | `/api/starrail/operations` | 同步 | 指令清单（自描述） |
| POST | `/api/starrail/ping` | 同步 | Mod 级连通性 |
| POST | `/api/starrail/driver-ping` | 同步 | 驱动级全链路连通性 |
| GET  | `/api/starrail/status` | 同步 | 驱动状态 + 体力数据 |
| GET  | `/api/starrail/power` | 同步 | 开拓力查询 current/reserve |
| GET  | `/api/starrail/daily-task/observe` | 同步 | 观察未完成实训任务 |
| POST | `/api/starrail/daily-task` | Job | 完整日常，可选 `{"taskIds":[...]}` |
| POST | `/api/starrail/daily-task/reward` | Job | 仅领奖 |
| POST | `/api/starrail/clear-power` | Job | 清体力 `{powerNum:0-30, selection:1-3, useReserve:bool}` |
| POST | `/api/starrail/execute` | 同步/Job | 通用入口 `{operate, params, targetClient?, timeout?}` |
| POST | `/api/starrail/target-client` | 会话 | 设置默认目标设备 `{targetClient:"设备名"}` |
| GET  | `/api/jobs/{jobId}` | 轮询 | 长操作进度与结果 |

`targetClient` 说明：多设备时，可在任意请求 body/query 里传 `targetClient`，
或先调 `/api/starrail/target-client` 设为会话默认。

---

## 6. 错误码与排查

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 401 未登录或会话已过期 | 无/过期 Cookie；token 过期且 refresh 失败 | 重新走统一登录（方式 A/B） |
| 502 与服务器通信失败 | WS 服务器不可达 | 检查 SERVER_HOST 配置与网络 |
| 502 指令未收到响应（timeout） | Mod 离线或未响应 | 确认 Mod 已启动并注册到 `mod:{uid}:starrail` |
| 422 参数校验失败 | powerNum 超 0-30 等 | 按 detail 字段提示修正 |
| 404 任务不存在或已被清理 | jobId 错误或任务已完成被清理 | 重新发起长操作 |
| 登录后停在 account.cabyss.cn 报错 | 复用了旧授权链接（nonce 一次性） | 回首页重新点击登录按钮，勿复用旧链接 |
| 前端显示"⚠️ 登录回跳未携带有效 token" | 回跳缺 token 参数 | 检查统一登录侧 redirectUrl 配置 |

---

## 7. 一键冒烟脚本

```bash
#!/usr/bin/env bash
# smoke-web-api.sh —— 接口层冒烟（不含游戏副作用），需先按"方式B"生成 cookie.txt
BASE=http://localhost:8765
pass=0; fail=0
check() {  # check <名称> <期望状态码> <curl命令...>
  local name=$1 want=$2; shift 2
  local got; got=$(curl -s -o /dev/null -w "%{http_code}" "$@")
  if [ "$got" = "$want" ]; then echo "PASS  $name ($got)"; pass=$((pass+1))
  else echo "FAIL  $name (want $want got $got)"; fail=$((fail+1)); fi
}

check "me(已登录)"          200 -b cookie.txt "$BASE/api/auth/me"
check "operations"          200 -b cookie.txt "$BASE/api/starrail/operations"
check "未登录被拒"          401 "$BASE/api/starrail/operations"
check "powerNum=31→422"    422 -b cookie.txt -X POST "$BASE/api/starrail/clear-power" \
  -H "Content-Type: application/json" -d '{"powerNum":31}'
check "未知job→404"        404 -b cookie.txt "$BASE/api/jobs/not-exist"
check "首页"                200 "$BASE/"
echo "----"; echo "pass=$pass fail=$fail"
```
