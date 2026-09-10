"""
崩坏：星穹铁道 自动化 Mod（逻辑端）。

StarRailMod 是 SmartPlayBuddy 的逻辑扩展节点（type="mod"），与设备端（type="client"）
的 starrail 驱动配合使用。驱动负责游戏内原子操作（截图、定位、点击、OCR），
Mod 负责高层业务编排（观察任务 → 逐项执行 → 领取奖励；查询体力 → 校验 → 清理）。

消息流（经服务端按 to 字段路由）：
    控制器 ──command(action="starrail")──▶ StarRailMod
    StarRailMod ──command(action="starrail")──▶ client:{userId}:{deviceName}
    客户端 starrail 驱动执行 ──response──▶ StarRailMod
    StarRailMod ──response──▶ 控制器

支持的指令 operate：
    ping                Mod 级连通性检查（不碰客户端，立即响应）
    driver/ping         驱动级连通性检查（转发到 client，验证全链路）
    status              驱动状态 + 体力数据
    game/running        查询游戏是否已启动（透传驱动 game/running）
    game/open           启动游戏并等待进入主界面（透传驱动 game/open）
    daily_task          完整日常流程（执行前检查游戏已启动；转发驱动 daily_task/start：
                        观察 → 逐项执行 → 领取奖励，完成后回查剩余任务）
    daily_task/observe  仅观察，返回未完成任务 id 列表（前端展示）
    daily_task/reward   仅领取每日实训奖励
    clear_power         清理开拓力（执行前检查游戏已启动；完成后回查体力）
    power/query         仅查询开拓力数据
"""

import asyncio
import os
import sys
from typing import Callable, Dict, Optional
from uuid import uuid4

# 确保 smartplaybuddy 优先解析到本仓库 src/（环境里可能有 SmartBuddy04/05/07 等多个
# editable 安装；无论 Mod 以何种方式启动（python -m / 直接 import / PyCharm），都先校正路径）
_WS_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SRC_DIR = os.path.join(_WS_ROOT, "src")
if os.path.isdir(_SRC_DIR) and _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from smartplaybuddy import i18n
from smartplaybuddy import log
from smartplaybuddy.mod import Mod

logger = log.logger.getChild("Mod").getChild("StarRail")


def _translate(key: str, **kwargs) -> str:
    """翻译查找，缺失时回退为键名本身，避免消息循环因缺翻译而崩溃。"""
    try:
        return i18n.translate(key, **kwargs)
    except KeyError:
        return key

# 每日实训任务 id → 驱动操作 映射（与 drivers/starrail/module/daily_task/DailyTask.py 中
# daily_task_dict 保持一致：2=委托派遣 9=万能合成台 10=拍照）
DAILY_TASK_OPS: Dict[int, str] = {
    2: "daily_task/entrust",
    9: "daily_task/mix",
    10: "daily_task/photo",
}

# 执行前必须确认游戏已启动的指令（否则截图/点击全部空跑）
GAME_REQUIRED_OPERATES = {"daily_task", "clear_power"}

GAME_NOT_RUNNING_MSG = (
    "游戏未启动，请先在「启动游戏」中启动《崩坏：星穹铁道》后再执行"
)


def _is_running(running_data) -> bool:
    """从 game/running 响应（已解开 result）提取 running 布尔值。"""
    if isinstance(running_data, dict) and "result" in running_data:
        running_data = running_data.get("result")
    return bool(running_data.get("running")) if isinstance(running_data, dict) else False


def map_task_id_to_operate(task_id) -> Optional[str]:
    """将任务 id 映射为 starrail 驱动的操作名；无对应处理时返回 None。"""
    try:
        return DAILY_TASK_OPS.get(int(task_id))
    except (TypeError, ValueError):
        return None


def _unwrap(resp, op: str):
    """校验 dispatch 结果并返回业务负载。

    兼容两种形式：
    - 完整驱动响应 {"status":"ok","result":X}（测试/直连场景）→ 返回 X
    - 客户端已解开的负载 X（真实链路：{"status","result"} 包装不跨 WebSocket）→ 透传
    error 结构（含 dispatch 超时）→ 抛异常
    """
    if isinstance(resp, dict) and resp.get("status") == "error":
        raise RuntimeError(f"{op} 驱动执行失败: {resp.get('message')}")
    if isinstance(resp, dict) and "result" in resp:
        return resp.get("result")
    return resp


# ======================================================================
# 业务编排（纯异步逻辑，dispatch 由调用方注入，便于单元测试）
# ======================================================================

async def execute_starrail_flow(operate: str, params: dict, dispatch: Callable,
                                notify: Optional[Callable] = None):
    """执行一个高层业务流。

    Args:
        operate: 指令名（daily_task / clear_power / status / ...）
        params:  指令参数
        dispatch: 异步分发函数 dispatch(op, params) -> 驱动响应 dict
        notify:  可选进度回调 notify(flow, step, detail) —— 长流程执行中推送事件

    Returns:
        统一响应结构 {"status": "ok", "result": {...}} 或 {"status": "error", ...}
    """
    params = dict(params or {})

    async def _emit(step: str, detail: str = None):
        if notify is not None:
            try:
                await notify(operate, step, detail)
            except Exception:
                pass

    if operate == "ping":
        # Mod 级连通性检查：不转发驱动，立即响应
        # （用于定位"控制器 → 服务器 → Mod"这一段链路是否正常）
        return {"status": "ok", "result": {"pong": True, "mod": "starrail"}}

    if operate == "driver/ping":
        # 驱动级连通性检查：转发到 client 的 starrail 驱动，验证全链路
        return {"status": "ok", "result": _unwrap(await dispatch("ping", params), "ping")}

    if operate == "status":
        status = _unwrap(await dispatch("status", params), "status")
        try:
            power = _unwrap(await dispatch("power/query", params), "power/query")
        except Exception as e:  # 查询体力失败不影响状态返回
            power = {"error": str(e)}
        return {"status": "ok", "result": {"driver": status, "power": power}}

    if operate == "game/running":
        # 查询游戏是否已启动（前端「启动游戏」页/功能前置检查用）
        return {"status": "ok", "result": _unwrap(await dispatch("game/running", params), "game/running")}

    if operate == "game/open":
        # 启动游戏并等待进入主界面（透传驱动 game/open，支持 wait_for_login 参数）
        await _emit("启动游戏")
        opened = _unwrap(await dispatch("game/open", params), "game/open")
        if isinstance(opened, dict):
            opened = opened.get("opened")
        await _emit("启动游戏流程结束")
        return {"status": "ok", "result": {"opened": bool(opened)}}

    # ---------- 游戏启动前置检查：未启动则拦截，不执行 ----------
    if operate in GAME_REQUIRED_OPERATES:
        try:
            running = _is_running(await dispatch("game/running", params))
        except Exception as e:
            logger.warning("game/running 检查失败，视为未启动: %s", e)
            running = False
        if not running:
            await _emit("游戏未启动，已停止执行")
            return {"status": "error", "message": GAME_NOT_RUNNING_MSG}

    if operate == "daily_task":
        # 完整日常流程：直接委托给 starrail 驱动的 daily_task/start，
        # 由驱动侧 start_daily_task() 完成「观察 → 逐项执行 → 领取奖励」全流程。
        await _emit("开始执行每日实训")
        started = _unwrap(await dispatch("daily_task/start", params), "daily_task/start")
        await _emit("每日实训完成")

        # 完成后回查剩余任务，透传给调用方（前端可据此刷新勾选区）；回查失败不影响主结果
        remaining = None
        try:
            observed = _unwrap(await dispatch("daily_task/observe", params), "daily_task/observe")
            if isinstance(observed, dict):
                remaining = list(observed.get("task_ids", []) or [])
        except Exception:
            pass

        return {"status": "ok", "result": {"started": started, "remaining": remaining}}

    if operate == "daily_task/observe":
        # 仅观察，返回未完成任务列表（前端展示用）
        await _emit("观察中")
        observed = _unwrap(await dispatch("daily_task/observe", params), "daily_task/observe")
        task_ids = observed.get("task_ids", []) if isinstance(observed, dict) else []
        return {
            "status": "ok",
            "result": {
                "task_ids": list(task_ids),
                "supported": sorted(DAILY_TASK_OPS.keys()),
            },
        }

    if operate == "daily_task/reward":
        await _emit("领取实训奖励")
        claimed = _unwrap(await dispatch("daily_task/reward", params), "daily_task/reward")
        return {"status": "ok", "result": {"claimed": claimed}}

    if operate == "power/query":
        return {"status": "ok", "result": _unwrap(await dispatch("power/query", params), "power/query")}

    if operate == "clear_power":
        #test
        logger.info(f"params_data:{params}")
        clear_params = dict(params)
        clear_params.setdefault("power_num", 0)  # 0 = 全部清完
        clear_params.setdefault("selection",1)#信用点
        clear_params.setdefault("use_reserve",False)

        count = "全部" if clear_params["power_num"] == 0 else f"{clear_params['power_num']} 次"
        await _emit(f"开始清理（{count}），等待驱动完成…")
        cleared = _unwrap(await dispatch("power/clear", clear_params), "power/clear")
        await _emit("清理完成")


        return {"status": "ok", "result": {"cleared": cleared}}

    return {"status": "error", "message": f"unknown starrail operate: {operate}"}


def _extract_current_power(power) -> Optional[int]:
    """从 power/query 响应（已解开 result）中提取当前开拓力数值。"""
    if not isinstance(power, dict):
        return None
    data = power.get("data")
    if not isinstance(data, dict):
        return None
    return data.get("current_power")


# ======================================================================
# Mod 节点
# ======================================================================

class StarRailMod(Mod):
    """星穹铁道自动化 Mod：接收高层指令 → 编排驱动操作 → 汇总响应。"""

    name = "starrail"

    def __init__(self, **config):
        self.target_client = config.get("target_client")          # 目标设备名（可选）
        self.user_id = config.get("user_id")                       # 用户 ID（可选，JWT 解析）
        # 默认 1 小时：游戏自动化操作（观察/清体力）可持续数分钟，
        # 短查询的超时由调用方（控制器/客户端等）各自兜底。
        self.default_timeout = float(config.get("default_timeout", 3600.0))
        self._pending: Dict[str, asyncio.Future] = {}
        self._tasks: set = set()                                   # 进行中的指令处理任务
        super().__init__(**config)

    # ---------------- 消息入口 ----------------

    async def main(self, msg) -> None:
        if msg.Type == "command" and msg.Action == self.name:
            # 关键：指令处理必须异步任务化，不能阻塞消息循环——
            # 否则循环在 await 流程期间无法 recv 客户端响应，造成死锁（响应永远收不到）。
            task = asyncio.get_running_loop().create_task(self._on_starrail_command(msg))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        elif msg.Type in ("response", "error"):
            fut = self._pending.pop(msg.RequestID, None)
            if fut is not None and not fut.done():
                if msg.Type == "error":
                    fut.set_result({"status": "error", "message": msg.Data})
                else:
                    fut.set_result(msg.Data)

    async def _on_starrail_command(self, msg):
        data = msg.Data if isinstance(msg.Data, dict) else {}
        operate = data.get("operate")
        params = data.get("params") if isinstance(data.get("params"), dict) else {}
        if not isinstance(data.get("params"), dict):
            # 兼容扁平格式 {"operate": ..., "power_num": ...}：
            # 除 operate 外的顶层字段全部视为参数
            params = {k: v for k, v in data.items() if k != "operate"}
        logger.info(f"收到指令数据 operate={operate} params={params}")
        if not operate:
            await self.Error.error("starrail 指令缺少 operate 字段", To=msg.From, RequestID=msg.RequestID)
            return
        logger.info(_translate("mod.starrail.command_received", operate=operate, sender=msg.From))

        async def _notify(flow, step, detail=None):
            """长流程进度事件，推送给指令发起方（如 Web 桥）。"""
            await self.conn.send(
                self.Message(Type="event", Action=self.name, To=msg.From,
                             Data={"state": "busy", "flow": flow, "step": step, "detail": detail}).to_json()
            )

        try:
            result = await execute_starrail_flow(
                operate, params,
                lambda op, p: self._dispatch(op, p, msg.From),
                notify=_notify,
            )
            await self.conn.send(
                self.Message(Type="response", Action=self.name, To=msg.From,
                             RequestID=msg.RequestID, Data=result).to_json()
            )
        except Exception as e:
            logger.error(_translate("mod.starrail.flow_failed", operate=operate, error=e), exc_info=True)
            await self.Error.error(f"{operate} 执行失败: {e}", To=msg.From, RequestID=msg.RequestID)

    # ---------------- 驱动分发 ----------------

    async def _dispatch(self, op: str, params: dict, requester: Optional[str]) -> dict:
        """向目标 client 发送 starrail 驱动操作，并等待其响应。"""
        target_id = self._resolve_client_id(requester, params.get("target_client"))
        logger.info("向 %s 发送驱动指令: %s", target_id, op)
        request_id = f"starrail:{op}:{uuid4().hex[:8]}"
        fut = asyncio.get_running_loop().create_future()
        self._pending[request_id] = fut

        payload = {"operate": op}
        for key, value in params.items():
            if key not in ("target_client", "timeout"):
                payload[key] = value

        await self.conn.send(
            self.Message(Type="command", Action=self.name, To=target_id,
                         RequestID=request_id, Data=payload).to_json()
        )
        timeout = float(params.get("timeout", self.default_timeout))
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(request_id, None)
            return {
                "status": "error",
                "message": (
                    f"等待客户端响应超时: {op} ({timeout}s)，目标 {target_id}。"
                    "请检查：① 该 Client 是否在线并连接服务器；"
                    "② Client 注册的 deviceName 是否与 --target-client 一致"
                    "（默认 deviceName 为空会被服务器分配 UUID，需在 client.py 中显式设置）；"
                    "③ Client 是否正被其他长任务占用（单连接串行处理）。"
                ),
            }

    def _resolve_client_id(self, requester: Optional[str], target: Optional[str]) -> str:
        """解析目标 client 的完整路由标识 client:{userId}:{deviceName}。"""
        if target and ":" in target:
            return target  # 已是完整标识，直接使用

        user_id = self.user_id
        if not user_id and requester:
            parts = str(requester).split(":")
            if len(parts) >= 2 and parts[1]:
                user_id = parts[1]

        if not user_id:
            raise ValueError(
                "无法确定 userId：请通过 --user-id 配置，或在指令 params 中传入完整 target_client (client:123:pc)"
            )
        device = target or self.target_client
        if not device:
            raise ValueError("缺少目标设备：请通过 --target-client 配置或在指令 params.target_client 中指定设备名")
        return f"client:{user_id}:{device}"

    def on_close(self):
        for fut in self._pending.values():
            if not fut.done():
                fut.set_result({"status": "error", "message": "连接已关闭"})
        self._pending.clear()
        super().on_close()
