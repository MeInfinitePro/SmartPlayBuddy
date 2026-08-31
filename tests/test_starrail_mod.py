"""StarRailMod 单元测试：业务编排（execute_starrail_flow）与消息分发（main）。

不依赖真实 WebSocket：使用 FakeConn 模拟连接，responder 模拟客户端驱动的响应。
"""
import asyncio
import base64
import json

import pytest

from mods.starrail import (
    StarRailMod,
    execute_starrail_flow,
    map_task_id_to_operate,
    DAILY_TASK_OPS,
)
from smartplaybuddy.ws.message import Message


# ======================================================================
# 纯逻辑：任务映射
# ======================================================================

def test_task_id_mapping():
    assert map_task_id_to_operate(2) == "daily_task/entrust"
    assert map_task_id_to_operate(9) == "daily_task/mix"
    assert map_task_id_to_operate(10) == "daily_task/photo"
    assert map_task_id_to_operate(99) is None
    assert map_task_id_to_operate("2") == "daily_task/entrust"
    assert map_task_id_to_operate("abc") is None
    assert map_task_id_to_operate(None) is None
    assert DAILY_TASK_OPS == {2: "daily_task/entrust", 9: "daily_task/mix", 10: "daily_task/photo"}


# ======================================================================
# 纯逻辑：业务编排（注入 dispatch）
# ======================================================================

def test_flow_ping():
    async def dispatch(op, params):
        return {"status": "ok", "result": {"pong": True, "op": op}}

    result = asyncio.run(execute_starrail_flow("ping", {}, dispatch))
    assert result["status"] == "ok"
    assert result["result"]["pong"] is True


def test_flow_daily_task_full_sequence():
    calls = []

    async def dispatch(op, params):
        calls.append(op)
        if op == "daily_task/observe":
            return {"status": "ok", "result": {"task_ids": [2, 9, 99, 10]}}
        return {"status": "ok", "result": {"done": True, "op": op}}

    result = asyncio.run(execute_starrail_flow("daily_task", {}, dispatch))
    assert result["status"] == "ok"
    r = result["result"]
    assert r["observed"] == [2, 9, 99, 10]
    assert [e["operate"] for e in r["executed"]] == [
        "daily_task/entrust", "daily_task/mix", None, "daily_task/photo",
    ]
    skipped = [e for e in r["executed"] if e["operate"] is None]
    assert skipped and skipped[0]["task_id"] == 99
    # 顺序：观察 → 2 → 9 → (99跳过) → 10 → 领奖
    assert calls == ["daily_task/observe", "daily_task/entrust", "daily_task/mix",
                     "daily_task/photo", "daily_task/reward"]


def test_flow_daily_task_no_tasks():
    async def dispatch(op, params):
        if op == "daily_task/observe":
            return {"status": "ok", "result": {"task_ids": []}}
        return {"status": "ok", "result": {"done": True}}

    result = asyncio.run(execute_starrail_flow("daily_task", {}, dispatch))
    assert result["result"]["observed"] == []
    assert result["result"]["executed"] == []


def test_flow_clear_power_insufficient():
    async def dispatch(op, params):
        return {"status": "ok", "result": {"data": {"current_power": 8, "max_power": 300, "reserve_power": 0}}}

    result = asyncio.run(execute_starrail_flow("clear_power", {}, dispatch))
    assert result["status"] == "ok"
    assert result["result"]["skipped"]
    assert result["result"]["current_power"] == 8


def test_flow_clear_power_ok_with_default_power_num():
    calls = []

    async def dispatch(op, params):
        calls.append((op, params))
        if op == "power/query":
            return {"status": "ok", "result": {"data": {"current_power": 120, "max_power": 300, "reserve_power": 0}}}
        return {"status": "ok", "result": {"started": True, "params": params}}

    result = asyncio.run(execute_starrail_flow("clear_power", {}, dispatch))
    assert result["status"] == "ok"
    assert result["result"]["cleared"]["started"] is True
    # power_num 未指定时默认 0（全部清完）
    assert calls[1] == ("power/clear", {"power_num": 0})


def test_flow_clear_power_respects_explicit_power_num():
    async def dispatch(op, params):
        if op == "power/query":
            return {"status": "ok", "result": {"data": {"current_power": 120, "max_power": 300, "reserve_power": 0}}}
        return {"status": "ok", "result": {"started": True}}

    result = asyncio.run(execute_starrail_flow("clear_power", {"power_num": 12}, dispatch))
    assert result["result"]["cleared"]["started"] is True


def test_flow_status():
    async def dispatch(op, params):
        if op == "status":
            return {"status": "ok", "result": {"driver": "starrail", "game_running": False}}
        return {"status": "ok", "result": {"data": {"current_power": 100, "max_power": 300}}}

    result = asyncio.run(execute_starrail_flow("status", {}, dispatch))
    assert result["status"] == "ok"
    assert result["result"]["driver"]["driver"] == "starrail"
    assert result["result"]["power"]["data"]["current_power"] == 100


def test_flow_unknown_operate():
    async def dispatch(op, params):
        return {"status": "ok"}

    result = asyncio.run(execute_starrail_flow("bogus_operate", {}, dispatch))
    assert result["status"] == "error"


# ======================================================================
# Mod 消息分发（FakeConn）
# ======================================================================

class FakeError:
    def __init__(self):
        self.calls = []

    async def error(self, data, To=None, RequestID=None):
        self.calls.append({"data": data, "to": To, "request_id": RequestID})


class FakeConn:
    """模拟 WebSocket 连接：记录发送的 JSON 消息，并模拟客户端驱动即时响应。"""

    def __init__(self, mod, responder=None):
        self.mod = mod
        self.sent = []
        self.responder = responder or (lambda op, data: {"status": "ok", "result": {"done": True, "op": op}})

    async def send(self, payload):
        self.sent.append(payload)
        try:
            d = json.loads(payload)
        except Exception:
            return
        rid = d.get("requestId")
        # 仅当是发给 client 的 starrail 驱动指令时才模拟响应
        if d.get("type") == "command" and d.get("action") == "starrail" and rid in self.mod._pending:
            try:
                data = json.loads(base64.b64decode(d["data"]))
            except Exception:
                return
            op = data.get("operate")
            resp = self.responder(op, data)
            fut = self.mod._pending[rid]
            if not fut.done():
                fut.set_result(resp)


def _make_mod(responder=None, user_id="123", target_client="pc"):
    """不经 __init__（避免真实建连）构造 StarRailMod 实例。"""
    mod = object.__new__(StarRailMod)
    mod.target_client = target_client
    mod.user_id = user_id
    mod.default_timeout = 5.0
    mod._pending = {}
    mod.Error = FakeError()
    mod.conn = FakeConn(mod, responder)
    return mod


def _decode(payload):
    d = json.loads(payload)
    if d.get("data"):
        try:
            return json.loads(base64.b64decode(d["data"]))
        except Exception:
            return d["data"]
    return None


def test_mod_command_ping_roundtrip():
    mod = _make_mod()
    msg = Message(Type="command", Action="starrail", From="mod:123:controller",
                  RequestID="req-1", Data={"operate": "ping", "params": {}})
    asyncio.run(mod.main(msg))

    # 第一条：发给 client 的驱动指令
    first = json.loads(mod.conn.sent[0])
    assert first["type"] == "command"
    assert first["action"] == "starrail"
    assert first["to"].startswith("client:123:")
    assert first["requestId"].startswith("starrail:ping:")

    # 最后一条：回给控制器的响应
    last = json.loads(mod.conn.sent[-1])
    assert last["type"] == "response"
    assert last["action"] == "starrail"
    assert last["to"] == "mod:123:controller"
    assert last["requestId"] == "req-1"
    data = _decode(mod.conn.sent[-1])
    assert data["status"] == "ok"
    assert data["result"]["op"] == "ping"


def test_mod_command_daily_task_flow():
    def responder(op, data):
        if op == "daily_task/observe":
            return {"status": "ok", "result": {"task_ids": [2, 9]}}
        return {"status": "ok", "result": {"done": True, "op": op}}

    mod = _make_mod(responder=responder)
    msg = Message(Type="command", Action="starrail", From="mod:123:controller",
                  RequestID="req-2",
                  Data={"operate": "daily_task", "params": {"target_client": "my-pc"}})
    asyncio.run(mod.main(msg))

    data = _decode(mod.conn.sent[-1])
    assert data["status"] == "ok"
    r = data["result"]
    assert r["observed"] == [2, 9]
    assert [e["operate"] for e in r["executed"]] == ["daily_task/entrust", "daily_task/mix"]
    assert r["claim"]["op"] == "daily_task/reward"

    # 目标解析：params.target_client 覆盖默认配置
    commands = [json.loads(p) for p in mod.conn.sent if json.loads(p)["type"] == "command"]
    assert all(c["to"] == "client:123:my-pc" for c in commands)


def test_mod_command_clear_power_insufficient():
    def responder(op, data):
        return {"status": "ok", "result": {"data": {"current_power": 5, "max_power": 300, "reserve_power": 0}}}

    mod = _make_mod(responder=responder)
    msg = Message(Type="command", Action="starrail", From="mod:123:controller",
                  RequestID="req-3", Data={"operate": "clear_power", "params": {}})
    asyncio.run(mod.main(msg))

    data = _decode(mod.conn.sent[-1])
    assert data["status"] == "ok"
    assert data["result"]["skipped"]
    assert data["result"]["current_power"] == 5
    # 不足 10 时不触发 power/clear
    commands = [json.loads(p) for p in mod.conn.sent if json.loads(p)["type"] == "command"]
    assert all("power/query" in json.loads(base64.b64decode(c["data"]))["operate"] for c in commands)


def test_mod_response_without_pending_ignored():
    mod = _make_mod()
    msg = Message(Type="response", Action="starrail", From="client:123:pc",
                  RequestID="unknown-rid", Data={"status": "ok"})
    asyncio.run(mod.main(msg))
    assert len(mod.conn.sent) == 0


def test_mod_error_response_resolves_pending():
    mod = _make_mod()

    async def scenario():
        fut = asyncio.get_running_loop().create_future()
        mod._pending["starrail:power/query:abc"] = fut
        msg = Message(Type="error", Action="error", From="client:123:pc",
                      RequestID="starrail:power/query:abc", Data="driver boom")
        await mod.main(msg)
        assert fut.done()
        assert fut.result() == {"status": "error", "message": "driver boom"}

    asyncio.run(scenario())


def test_mod_command_missing_operate():
    mod = _make_mod()
    msg = Message(Type="command", Action="starrail", From="mod:123:controller",
                  RequestID="req-x", Data={})
    asyncio.run(mod.main(msg))
    assert len(mod.Error.calls) == 1
    assert mod.Error.calls[0]["request_id"] == "req-x"
    assert "operate" in mod.Error.calls[0]["data"]


def test_mod_command_unknown_operate():
    mod = _make_mod()
    msg = Message(Type="command", Action="starrail", From="mod:123:controller",
                  RequestID="req-y", Data={"operate": "bogus", "params": {}})
    asyncio.run(mod.main(msg))
    data = _decode(mod.conn.sent[-1])
    assert data["status"] == "error"


# ======================================================================
# 目标解析
# ======================================================================

def test_resolve_client_id_with_config_user():
    mod = _make_mod(user_id="123", target_client="pc")
    assert mod._resolve_client_id("mod:9:controller", None) == "client:123:pc"
    assert mod._resolve_client_id("mod:9:controller", "my-pc") == "client:123:my-pc"
    assert mod._resolve_client_id(None, "client:7:direct") == "client:7:direct"


def test_resolve_client_id_from_requester():
    mod = _make_mod(user_id=None, target_client="pc")
    assert mod._resolve_client_id("mod:9:controller", None) == "client:9:pc"


def test_resolve_client_id_missing_user():
    mod = _make_mod(user_id=None, target_client=None)
    with pytest.raises(ValueError):
        mod._resolve_client_id(None, None)
    with pytest.raises(ValueError):
        mod._resolve_client_id(None, "pc")
