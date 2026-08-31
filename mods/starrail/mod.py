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
    ping                驱动连通性检查
    status              驱动状态 + 体力数据
    daily_task          完整日常流程（观察 → 逐项执行 → 领取奖励）
    daily_task/reward   仅领取每日实训奖励
    clear_power         清理开拓力（含安全校验与后备体力决策）
    power/query         仅查询开拓力数据
"""

import asyncio
from typing import Callable, Dict, Optional
from uuid import uuid4

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


def map_task_id_to_operate(task_id) -> Optional[str]:
    """将任务 id 映射为 starrail 驱动的操作名；无对应处理时返回 None。"""
    try:
        return DAILY_TASK_OPS.get(int(task_id))
    except (TypeError, ValueError):
        return None


def _unwrap(resp, op: str):
    """解开驱动响应外层 {"status": ..., "result": ...}，返回 result 负载。

    驱动返回 status=error 时抛出异常，由上层统一转为 error 响应。
    """
    if isinstance(resp, dict) and resp.get("status") == "error":
        raise RuntimeError(f"{op} 驱动执行失败: {resp.get('message')}")
    if isinstance(resp, dict):
        return resp.get("result")
    return resp


# ======================================================================
# 业务编排（纯异步逻辑，dispatch 由调用方注入，便于单元测试）
# ======================================================================

async def execute_starrail_flow(operate: str, params: dict, dispatch: Callable):
    """执行一个高层业务流。

    Args:
        operate: 指令名（daily_task / clear_power / status / ...）
        params:  指令参数
        dispatch: 异步分发函数 dispatch(op, params) -> 驱动响应 dict

    Returns:
        统一响应结构 {"status": "ok", "result": {...}} 或 {"status": "error", ...}
    """
    params = dict(params or {})

    if operate == "ping":
        return {"status": "ok", "result": _unwrap(await dispatch("ping", params), "ping")}

    if operate == "status":
        status = _unwrap(await dispatch("status", params), "status")
        try:
            power = _unwrap(await dispatch("power/query", params), "power/query")
        except Exception as e:  # 查询体力失败不影响状态返回
            power = {"error": str(e)}
        return {"status": "ok", "result": {"driver": status, "power": power}}

    if operate == "daily_task":
        observed = _unwrap(await dispatch("daily_task/observe", params), "daily_task/observe")
        task_ids = observed.get("task_ids", []) if isinstance(observed, dict) else []
        executed = []
        for tid in task_ids:
            op = map_task_id_to_operate(tid)
            if op is None:
                executed.append({"task_id": tid, "operate": None, "skipped": "no handler"})
                continue
            executed.append({
                "task_id": tid,
                "operate": op,
                "result": _unwrap(await dispatch(op, params), op),
            })
        claimed = _unwrap(await dispatch("daily_task/reward", params), "daily_task/reward")
        return {
            "status": "ok",
            "result": {
                "observed": list(task_ids),
                "executed": executed,
                "claim": claimed,
            },
        }

    if operate == "daily_task/reward":
        claimed = _unwrap(await dispatch("daily_task/reward", params), "daily_task/reward")
        return {"status": "ok", "result": {"claimed": claimed}}

    if operate == "power/query":
        return {"status": "ok", "result": _unwrap(await dispatch("power/query", params), "power/query")}

    if operate == "clear_power":
        power = _unwrap(await dispatch("power/query", params), "power/query")
        current = _extract_current_power(power)
        if current is not None and current < 10:
            return {
                "status": "ok",
                "result": {"skipped": "current_power < 10，无需清理", "current_power": current, "power": power},
            }
        clear_params = dict(params)
        clear_params.setdefault("power_num", 0)  # 0 = 全部清完
        cleared = _unwrap(await dispatch("power/clear", clear_params), "power/clear")
        return {"status": "ok", "result": {"power": power, "cleared": cleared}}

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
        self.default_timeout = float(config.get("default_timeout", 180.0))
        self._pending: Dict[str, asyncio.Future] = {}
        super().__init__(**config)

    # ---------------- 消息入口 ----------------

    async def main(self, msg) -> None:
        if msg.Type == "command" and msg.Action == self.name:
            await self._on_starrail_command(msg)
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
        if not operate:
            await self.Error.error("starrail 指令缺少 operate 字段", To=msg.From, RequestID=msg.RequestID)
            return
        logger.info(_translate("mod.starrail.command_received", operate=operate, sender=msg.From))
        try:
            result = await execute_starrail_flow(
                operate, params, lambda op, p: self._dispatch(op, p, msg.From)
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
            return {"status": "error", "message": f"等待客户端响应超时: {op} ({timeout}s)"}

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
