"""
SmartPlayBuddy 星穹铁道前端 —— FastAPI Web 桥接服务。

职责：
1. 统一登录回调：作为统一登录验证前端验证成功后的跳转目标，
   接收 accessToken / refreshToken / expiresIn（与客户端 user/login.py 的
   回调契约完全一致），建立会话。本服务不提供登录页面，复用已有登录验证。
2. REST API：为星穹铁道 Mod 的全部指令（daily_task / clear_power / ...）
   提供 HTTP 接口，供前端与外部测试工具（curl / Postman）使用。
3. 静态托管：托管 Vue 前端构建产物（web/frontend/dist）。

启动（项目根目录）：
    python web/backend/app.py                 # 默认 0.0.0.0:8765
    python web/backend/app.py --port 9000     # 指定端口

统一登录跳转地址：
    {SERVER_HOST}/api/user/auth/authorize?redirectUrl={本服务地址}/api/auth/callback
"""

import argparse
import asyncio
import base64
import json
import os
import sys
import time
import uuid
from typing import Optional

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# 让 smartplaybuddy 优先解析到本仓库 src/（与 mods 的处理一致）
_WEB_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC_DIR = os.path.join(os.path.dirname(_WEB_ROOT), "src")
if os.path.isdir(_SRC_DIR) and _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from smartplaybuddy.config import SERVER_HOST, VERSION  # noqa: E402

from bridge import (  # noqa: E402
    ALL_OPERATES, GAME_OPEN_TIMEOUT, JOB_TIMEOUT, SYNC_OPERATES, SYNC_TIMEOUT,
    StarRailBridge,
)

app = FastAPI(title="SmartPlayBuddy StarRail Web", version=VERSION)
bridge = StarRailBridge()

SESSION_COOKIE = "spb_session"
# 内存会话表：sid -> {"access_token","refresh_token","user_id","expires_at","target_client"}
SESSIONS: dict = {}

FRONTEND_DIR = os.path.join(_WEB_ROOT, "frontend")
# Vue 构建产物目录（npm run build 产出；后端仅托管 dist，不托管源码）
FRONTEND_DIST = os.path.join(FRONTEND_DIR, "dist")


@app.middleware("http")
async def _no_cache_frontend(request: Request, call_next):
    """开发期前端资源禁用缓存，避免浏览器命中旧版 HTML/JS 导致 DOM 结构不匹配。"""
    resp = await call_next(request)
    path = request.url.path
    if path in ("/", "/index.html") or path.endswith((".html", ".js", ".css")):
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


# ======================================================================
# JWT / Token 工具（与 mods/starrail/__main__.py、user/login.py 对齐）
# ======================================================================

def decode_jwt_payload(token: str) -> dict:
    """解析 JWT payload（不验签，仅供路由/过期判断；验签由服务端负责）。"""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return {}


def decode_user_id(access_token: str) -> Optional[str]:
    data = decode_jwt_payload(access_token)
    for key in ("sub", "userId", "uid", "id", "user_id"):
        if data.get(key):
            return str(data[key])
    return None


def token_expired(access_token: str) -> bool:
    exp = decode_jwt_payload(access_token).get("exp")
    return isinstance(exp, (int, float)) and time.time() >= exp


def refresh_tokens(refresh_token: str) -> Optional[dict]:
    """调用服务端刷新接口换取新 token（与 user/login.py 的 refresh_login 对齐）。"""
    import urllib.request
    try:
        req = urllib.request.Request(
            f"{SERVER_HOST}/api/user/auth/refresh",
            data=json.dumps({"refreshToken": refresh_token}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read())
        return {
            "access_token": data["accessToken"],
            "refresh_token": data.get("refreshToken", refresh_token),
            "expires_in": data.get("expiresIn", 0),
        }
    except Exception:
        return None


# ======================================================================
# 会话依赖
# ======================================================================

def _resolve_session(request: Request) -> Optional[dict]:
    sid = request.cookies.get(SESSION_COOKIE)
    if not sid or sid not in SESSIONS:
        return None
    sess = SESSIONS[sid]
    # access token 过期时尝试静默刷新（复用已有登录验证的 refresh 接口）
    if token_expired(sess["access_token"]) and sess.get("refresh_token"):
        new = refresh_tokens(sess["refresh_token"])
        if new:
            sess.update(new)
            sess["user_id"] = decode_user_id(sess["access_token"]) or sess["user_id"]
            sess["expires_at"] = time.time() + new["expires_in"]
    if token_expired(sess["access_token"]):
        return None
    return sess


async def require_auth(request: Request) -> dict:
    sess = _resolve_session(request)
    if sess is None:
        raise HTTPException(status_code=401, detail="未登录或会话已过期，请通过统一登录重新进入")
    return sess


def _resolve_iam_login_url(redirect: str) -> dict:
    """调用服务端 authorize 接口换取真实的统一登录页地址。

    服务端 /api/user/auth/authorize 返回 JSON {"url": ...}（而非重定向），
    与客户端 user/login.py 的处理方式一致：必须先解析出 url 再跳转。
    每次调用都会生成新的 nonce / PKCE 会话，因此需在登录时实时获取。
    """
    import urllib.parse
    import urllib.request
    endpoint = (f"{SERVER_HOST}/api/user/auth/authorize"
                f"?redirectUrl={urllib.parse.quote(redirect, safe='')}")
    try:
        with urllib.request.urlopen(endpoint, timeout=15) as resp:
            data = json.loads(resp.read())
        url = data.get("url")
        if url:
            return {"ok": True, "loginUrl": url}
        return {"ok": False, "error": f"服务端未返回 url: {data}"}
    except Exception as e:
        return {"ok": False, "error": f"请求服务端 authorize 失败: {e}"}


def _auth_login_url(request: Request) -> dict:
    """构造统一登录跳转地址：验证成功后回跳本服务 /api/auth/callback。"""
    redirect = f"{str(request.base_url).rstrip('/')}/api/auth/callback"
    return _resolve_iam_login_url(redirect)


# ======================================================================
# 认证 API
# ======================================================================

@app.get("/api/auth/me")
async def auth_me(request: Request):
    """会话探测：前端据此决定展示功能页还是“去统一登录”。"""
    sess = _resolve_session(request)
    if sess is None:
        resolved = _auth_login_url(request)
        return {"authenticated": False, **resolved}
    return {
        "authenticated": True,
        "userId": sess.get("user_id"),
        "expiresAt": sess.get("expires_at"),
        "targetClient": sess.get("target_client"),
    }


@app.get("/api/auth/login-url")
async def auth_login_url(request: Request):
    """返回统一登录跳转地址（复用已有登录验证，本服务不做登录页）。"""
    return _auth_login_url(request)


@app.get("/api/auth/callback")
async def auth_callback(accessToken: Optional[str] = None,
                        refreshToken: Optional[str] = None,
                        expiresIn: int = 0):
    """统一登录验证成功后的回跳端点（契约与客户端本地回调一致）。"""
    if not accessToken:
        return RedirectResponse("/?authError=missing_token")
    sid = uuid.uuid4().hex
    SESSIONS[sid] = {
        "access_token": accessToken,
        "refresh_token": refreshToken or "",
        "user_id": decode_user_id(accessToken),
        "expires_at": time.time() + int(expiresIn or 0),
        "target_client": SESSIONS.get(sid, {}).get("target_client"),
    }
    resp = RedirectResponse("/")
    resp.set_cookie(SESSION_COOKIE, sid, httponly=True, samesite="lax",
                    max_age=30 * 24 * 3600)
    return resp


@app.post("/api/auth/logout")
async def auth_logout(request: Request):
    sid = request.cookies.get(SESSION_COOKIE)
    if sid:
        SESSIONS.pop(sid, None)
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(SESSION_COOKIE)
    return resp


# ======================================================================
# 星穹铁道 API（供前端与测试工具使用）
# ======================================================================

class ExecuteBody(BaseModel):
    operate: str = Field(..., description="starrail 指令名")
    params: dict = Field(default_factory=dict, description="指令参数")
    targetClient: Optional[str] = Field(None, description="目标设备名（缺省用会话默认）")
    timeout: Optional[float] = Field(None, description="超时秒数")


class ClearPowerBody(BaseModel):
    powerNum: int = Field(0, ge=0, le=30, description="清体力计划：0=全部清完，N=N×10 点开拓力")
    selection: int = Field(1, ge=1, le=3, description="1=信用点 2=角色经验 3=光锥经验")
    useReserve: bool = Field(True, description="是否使用后备开拓力")
    targetClient: Optional[str] = None


class DailyTaskBody(BaseModel):
    taskIds: Optional[list] = Field(None, description="仅执行指定任务 id（如 [2,9,10]），缺省全部")
    targetClient: Optional[str] = None


class GameOpenBody(BaseModel):
    waitForLogin: Optional[bool] = Field(True, description="启动后是否等待并点击登录进入主界面")
    targetClient: Optional[str] = None


class TargetClientBody(BaseModel):
    targetClient: str = Field(..., description="目标客户端设备名（client 端 deviceName）")


def _merge_params(sess: dict, body_params: dict, target_client: Optional[str]) -> dict:
    params = dict(body_params or {})
    if target_client:
        params.setdefault("target_client", target_client)
    elif sess.get("target_client"):
        params.setdefault("target_client", sess["target_client"])
    return params


@app.get("/api/starrail/operations")
async def list_operations(_: dict = Depends(require_auth)):
    """列出可用的 starrail 指令（测试接口自描述）。"""
    return {
        "operates": sorted(ALL_OPERATES),
        "syncOperates": sorted(SYNC_OPERATES),
        "jobOperates": sorted(ALL_OPERATES - SYNC_OPERATES),
        "docs": {
            "ping": "Mod 级连通性检查",
            "driver/ping": "驱动级连通性检查（全链路）",
            "status": "驱动状态 + 体力数据",
            "game/running": "查询游戏是否已启动",
            "game/open": "启动游戏并等待进入主界面",
            "daily_task": "完整日常流程（执行前检查游戏已启动；观察→逐项执行→领奖→回查剩余）",
            "daily_task/observe": "仅观察未完成任务",
            "daily_task/reward": "仅领取实训奖励",
            "power/query": "查询开拓力数据",
            "clear_power": "清理开拓力（执行前检查游戏已启动；power_num 0-30，0=全部清完）",
        },
    }


@app.post("/api/starrail/execute")
async def starrail_execute(body: ExecuteBody, sess: dict = Depends(require_auth)):
    """通用指令入口：任意 starrail operate。短操作同步返回，长操作返回 jobId。"""
    if body.operate not in ALL_OPERATES:
        raise HTTPException(400, f"未知 operate: {body.operate}，可用: {sorted(ALL_OPERATES)}")
    params = _merge_params(sess, body.params, body.targetClient)
    if body.operate in SYNC_OPERATES:
        try:
            result = await bridge.execute_sync(
                sess["access_token"], sess["user_id"], body.operate, params,
                timeout=body.timeout or SYNC_TIMEOUT)
        except Exception as e:
            raise HTTPException(502, f"与服务器通信失败: {e}")
        if result.get("type") != "response":
            raise HTTPException(502, f"指令未收到响应: {result.get('type')}")
        return {"mode": "sync", "result": result.get("data")}
    job = bridge.start_job(sess["access_token"], sess["user_id"], body.operate, params,
                           timeout=body.timeout or JOB_TIMEOUT)
    return {"mode": "job", "jobId": job.id}


@app.post("/api/starrail/ping")
async def starrail_ping(body: ExecuteBody | None = None, sess: dict = Depends(require_auth)):
    params = _merge_params(sess, body.params if body else {}, None)
    result = await bridge.execute_sync(sess["access_token"], sess["user_id"], "ping", params)
    return {"mode": "sync", "result": result.get("data")}


@app.post("/api/starrail/driver-ping")
async def starrail_driver_ping(body: ExecuteBody | None = None, sess: dict = Depends(require_auth)):
    params = _merge_params(sess, body.params if body else {}, None)
    result = await bridge.execute_sync(sess["access_token"], sess["user_id"], "driver/ping", params)
    return {"mode": "sync", "result": result.get("data")}


@app.get("/api/starrail/status")
async def starrail_status(request: Request, sess: dict = Depends(require_auth)):
    params = _merge_params(sess, {}, request.query_params.get("targetClient"))
    result = await bridge.execute_sync(sess["access_token"], sess["user_id"], "status", params)
    return {"mode": "sync", "result": result.get("data")}


def _unwrap_mod_result(result: dict) -> dict:
    """从 bridge 响应中解开 Mod 业务负载：{"type","data":{"status","result":X}} → X。"""
    data = result.get("data") if isinstance(result, dict) else None
    if isinstance(data, dict) and "result" in data:
        payload = data.get("result")
        return payload if isinstance(payload, dict) else {}
    return data if isinstance(data, dict) else {}


@app.get("/api/starrail/game/running")
async def starrail_game_running(request: Request, sess: dict = Depends(require_auth)):
    """查询游戏是否已启动（前端每日实训/清体力按钮点击前的前置检查）。"""
    params = _merge_params(sess, {}, request.query_params.get("targetClient"))
    result = await bridge.execute_sync(sess["access_token"], sess["user_id"],
                                       "game/running", params)
    running = bool(_unwrap_mod_result(result).get("running"))
    return {"mode": "sync", "running": running}


@app.post("/api/starrail/game/open")
async def starrail_game_open(body: GameOpenBody | None = None,
                             sess: dict = Depends(require_auth)):
    """启动游戏（同步等待进入主界面；首次启动可能需全盘搜索游戏路径，超时较宽）。"""
    params = _merge_params(sess, {}, body.targetClient if body else None)
    if body is not None and body.waitForLogin is not None:
        params["wait_for_login"] = body.waitForLogin
    result = await bridge.execute_sync(sess["access_token"], sess["user_id"],
                                       "game/open", params, timeout=GAME_OPEN_TIMEOUT)
    opened = bool(_unwrap_mod_result(result).get("opened"))
    return {"mode": "sync", "opened": opened}


@app.get("/api/starrail/power")
async def starrail_power(request: Request, sess: dict = Depends(require_auth)):
    """查询当前开拓力（current_power / reserve_power）。"""
    params = _merge_params(sess, {}, request.query_params.get("targetClient"))
    result = await bridge.execute_sync(sess["access_token"], sess["user_id"], "power/query", params)
    return {"mode": "sync", "result": result.get("data")}


@app.get("/api/starrail/daily-task/observe")
async def starrail_daily_observe(request: Request, sess: dict = Depends(require_auth)):
    """观察未完成的每日实训任务（前端展示 + 勾选）。"""
    params = _merge_params(sess, {}, request.query_params.get("targetClient"))
    result = await bridge.execute_sync(sess["access_token"], sess["user_id"],
                                       "daily_task/observe", params)
    return {"mode": "sync", "result": result.get("data")}


@app.post("/api/starrail/daily-task")
async def starrail_daily_task(body: DailyTaskBody, sess: dict = Depends(require_auth)):
    """完整日常流程（长操作，返回 jobId）：观察 → 逐项执行 → 领取奖励。"""
    params = _merge_params(sess, {}, body.targetClient)
    if body.taskIds:
        params["task_ids"] = body.taskIds
    job = bridge.start_job(sess["access_token"], sess["user_id"], "daily_task", params)
    return {"mode": "job", "jobId": job.id}


@app.post("/api/starrail/daily-task/reward")
async def starrail_daily_reward(body: DailyTaskBody | None = None,
                                sess: dict = Depends(require_auth)):
    job = bridge.start_job(sess["access_token"], sess["user_id"], "daily_task/reward",
                           _merge_params(sess, {}, body.targetClient if body else None))
    return {"mode": "job", "jobId": job.id}


@app.post("/api/starrail/clear-power")
async def starrail_clear_power(body: ClearPowerBody, sess: dict = Depends(require_auth)):
    """清体力（长操作，返回 jobId）。

    powerNum 语义（与 Mod / 驱动对齐）：0 = 全部清完；N = 清 N 次 ×10 开拓力，
    前端限定 0-30（即 0-300 点）。
    """
    params = _merge_params(sess, {
        "power_num": body.powerNum,
        "selection": body.selection,
        "use_reserve": body.useReserve,
    }, body.targetClient)
    job = bridge.start_job(sess["access_token"], sess["user_id"], "clear_power", params)
    return {"mode": "job", "jobId": job.id}


@app.post("/api/starrail/target-client")
async def set_target_client(body: TargetClientBody, request: Request,
                            sess: dict = Depends(require_auth)):
    """设置当前会话默认目标设备名（client 端 deviceName）。"""
    sid = request.cookies.get(SESSION_COOKIE)
    if sid in SESSIONS:
        SESSIONS[sid]["target_client"] = body.targetClient
    return {"ok": True, "targetClient": body.targetClient}


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str, _: dict = Depends(require_auth)):
    """轮询长操作任务：status(running/ok/error) + events(进度) + result。"""
    job = bridge.get_job(job_id)
    if job is None:
        raise HTTPException(404, "任务不存在或已被清理")
    return job.to_dict()


# ======================================================================
# 静态托管（纯 HTML/JS 前端，免构建；API 路由已先注册，优先匹配）
# ======================================================================

# 静态托管：Vue 前端构建产物（web/frontend/dist）。
# API 路由已先注册，优先匹配；dist 不存在时（未执行 npm run build）给出提示。
if os.path.isdir(FRONTEND_DIST):
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
else:
    print(
        "[web] 未找到前端构建产物 web/frontend/dist。"
        "请先执行：cd web/frontend && npm install && npm run build",
        flush=True,
    )


def main():
    parser = argparse.ArgumentParser(description="SmartPlayBuddy 星穹铁道 Web 桥接服务")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
