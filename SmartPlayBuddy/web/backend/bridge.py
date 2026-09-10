"""
星穹铁道 Web 桥接层 —— 与服务端 WebSocket 通信的指令执行器。

设计（复用 mods/starrail/controller.py 的成熟模式）：
- 每个指令创建一条临时 WS 连接（携带用户 JWT），向 mod:{userId}:starrail
  发送 command(action="starrail")，等待匹配 RequestID 的 response/error 后关闭。
- 长流程（daily_task / clear_power）期间 Mod 会推送 Type="event" 的进度事件，
  全部收集进 job.events，前端轮询展示。
- 后台 Job 机制：HTTP 请求立即返回 job_id，避免长操作占死 HTTP 连接。
"""

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional
#test1
import websockets

from smartplaybuddy.config import WS_URL

# 短操作（同步等待）与长操作（后台 Job）划分
SYNC_OPERATES = {"ping", "driver/ping", "status", "power/query", "daily_task/observe",
                 "game/running", "game/open"}
ALL_OPERATES = SYNC_OPERATES | {"daily_task", "daily_task/reward", "clear_power"}

SYNC_TIMEOUT = 180.0        # 短操作默认超时（观察任务需截图 + OCR，耗时略长）
JOB_TIMEOUT = 3600.0        # 长操作默认超时（清体力可能跑几十分钟）
GAME_OPEN_TIMEOUT = 300.0   # 启动游戏超时（首次全盘搜索游戏路径可能较久）


@dataclass
class Job:
    id: str
    user_id: str
    operate: str
    params: dict
    status: str = "running"                      # running / ok / error
    events: list = field(default_factory=list)   # [{"flow","step","detail","ts"}]
    result: Optional[dict] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "jobId": self.id,
            "operate": self.operate,
            "params": self.params,
            "status": self.status,
            "events": self.events,
            "result": self.result,
            "error": self.error,
            "createdAt": self.created_at,
        }


class StarRailBridge:
    """负责向 starrail Mod 发送指令：短操作同步返回，长操作后台 Job。"""

    def __init__(self):
        self.jobs: dict[str, Job] = {}
        self._tasks: set = set()

    # ---------------- 对外入口 ----------------

    async def execute_sync(self, access_token: str, user_id: str,
                           operate: str, params: dict,
                           timeout: float = SYNC_TIMEOUT) -> dict:
        """执行短操作，阻塞直到响应（HTTP 请求内直接 await）。"""
        return await self._run_command(
            access_token, user_id, operate, params, timeout,
            events=None,
        )

    def start_job(self, access_token: str, user_id: str,
                  operate: str, params: dict,
                  timeout: float = JOB_TIMEOUT) -> Job:
        """启动长操作后台任务，立即返回 Job 供前端轮询。"""

        job = Job(id=f"job-{uuid.uuid4().hex[:12]}", user_id=user_id,
                  operate=operate, params=dict(params))
        self.jobs[job.id] = job

        async def _runner():
            try:
                result = await self._run_command(
                    access_token, user_id, operate, params, timeout,
                    events=job.events,
                )
                # _run_command 返回 {"type": ..., "data": ...}
                if result.get("type") == "response":
                    job.result = result.get("data")
                    job.status = "ok" if (job.result or {}).get("status") == "ok" else "error"
                    if job.status == "error":
                        job.error = (job.result or {}).get("message", "执行失败")
                elif result.get("type") == "error":
                    job.status = "error"
                    job.error = f"服务端返回错误: {result.get('data')}"
                else:
                    job.status = "error"
                    job.error = "连接中断或响应超时，未能收到结果"
            except Exception as e:  # 兜底：任何异常都不能让 job 悬在 running
                job.status = "error"
                job.error = str(e)

        task = asyncio.get_running_loop().create_task(_runner())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job

    def get_job(self, job_id: str) -> Optional[Job]:
        return self.jobs.get(job_id)

    def cleanup_jobs(self, max_age: float = 86400.0):
        """清理超过 max_age 秒的已完成 Job，防止内存无限增长。"""
        now = time.time()
        for jid in [j for j, job in self.jobs.items()
                    if job.status != "running" and now - job.created_at > max_age]:
            self.jobs.pop(jid, None)

    # ---------------- 核心指令执行 ----------------

    async def _run_command(self, access_token: str, user_id: str,
                           operate: str, params: dict, timeout: float,
                           events: Optional[list]) -> dict:
        """连接一次 → 发送指令 → 收集事件 → 等待匹配 RequestID 的响应 → 关闭。

        帧格式全部复用项目 Message 协议（Data 走 Base64 编解码），
        与 mods/starrail/controller.py 保持一致。
        """
        from smartplaybuddy import config as app_config
        from smartplaybuddy.ws.message import Message

        request_id = f"web-{uuid.uuid4().hex[:12]}"
        target = f"mod:{user_id}:starrail"
        headers = {"Authorization": f"Bearer {access_token}"}
        status = {
            "device": {
                "type": "mod",
                # 每次 job 用唯一设备名：并发长操作时避免“同用户同设备名已在
                # 线”被服务器拒绝/互顶，导致本次 job 收不到 Mod 回包。
                "deviceName": f"starrail-web-bridge-{uuid.uuid4().hex[:8]}",
                "deviceInfo": "SmartPlayBuddy star rail web bridge",
                "platform": "web-backend",
                "machine": "",
                "appVersion": app_config.VERSION,
            }
        }

        conn = await websockets.connect(WS_URL, additional_headers=headers,
                                        max_size=None, compression=None)
        try:
            # 向服务端声明身份（session/claim，与 StarRailController 一致）
            await conn.send(Message(Type="session", Action="claim", Data=status).to_json())

            # 契约格式与 controller.py / tests 保持一致：
            # Data = {"operate": ..., "params": {...}}（嵌套结构）。
            # 之前是扁平合并（operate 与参数混在同一层），导致 mod 端
            # data.get("params") 取不到，参数全部丢失。
            params_out = {k: v for k, v in (params or {}).items() if k != "timeout"}
            # 关键：显式把本连接的等待时限下发给 Mod，覆盖 Mod 启动时的短默认值
            # （--timeout 若不传，Mod 端单次驱动操作只有默认 180s）。
            # 清体力/完整日常可达几十分钟，不注入的话 Mod 会在驱动真正完成前
            # 判超时并返回 error，前端表现为"执行完了但拿不到结果/状态"。
            if timeout is not None:
                params_out.setdefault("timeout", float(timeout))
            payload = {"operate": operate, "params": params_out}
            await conn.send(Message(Type="command", Action="starrail", To=target,
                                    RequestID=request_id, Data=payload).to_json())

            deadline = time.time() + timeout
            while time.time() < deadline:
                try:
                    raw = await asyncio.wait_for(conn.recv(),
                                                 timeout=max(0.1, deadline - time.time()))
                except asyncio.TimeoutError:
                    return {"type": "timeout", "data": None}

                if isinstance(raw, bytes):
                    continue  # 本场景响应不含二进制帧

                try:
                    msg = Message.from_json(json.loads(raw))
                except Exception:
                    continue

                # 进度事件：Mod 长流程推送（无 RequestID，按当前 job 收集）
                if msg.Type == "event" and events is not None:
                    data = msg.Data if isinstance(msg.Data, dict) else {}
                    events.append({
                        "flow": data.get("flow"),
                        "step": data.get("step"),
                        "detail": data.get("detail"),
                        "ts": time.time(),
                    })
                    continue

                # 匹配的响应 / 错误
                if msg.Type in ("response", "error") and msg.RequestID == request_id:
                    return {"type": msg.Type, "data": msg.Data}
            return {"type": "timeout", "data": None}
        finally:
            try:
                await conn.close()
            except Exception:
                pass
