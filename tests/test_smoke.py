"""冒烟测试：驱动注册发现、真实驱动子进程 IPC、mod↔driver 一致性。"""
import base64
import json
import os
import queue
import struct
import subprocess
import sys

import pytest

_HEADER_FMT = "<BII"


def _send_frame(stream, msg: dict):
    payload = json.dumps(msg).encode("utf-8")
    stream.write(struct.pack(_HEADER_FMT, 0, len(payload), 0) + payload)
    stream.flush()


def _recv_frame(stream, timeout=60.0):
    """读取一帧。返回 (meta dict, binary bytes)。"""
    import time
    deadline = time.time() + timeout
    header = b""
    while len(header) < 9:
        chunk = stream.read(9 - len(header))
        if not chunk:
            return None, b""
        header += chunk
        if time.time() > deadline:
            raise TimeoutError("等待帧超时")
    _, json_len, bin_len = struct.unpack(_HEADER_FMT, header)
    json_bytes = b""
    while len(json_bytes) < json_len:
        chunk = stream.read(json_len - len(json_bytes))
        if not chunk:
            return None, b""
        json_bytes += chunk
    body = b""
    if bin_len:
        body = stream.read(bin_len)
    return json.loads(json_bytes.decode("utf-8")), body


def test_smoke_registry_discovers_starrail_driver(src_dir):
    """驱动注册表扫描应发现 starrail 插件及其动作。"""
    import importlib
    reg_mod = importlib.import_module("smartplaybuddy.drivers.registry")

    reg = reg_mod.DriverRegistry()
    reg.scan()
    assert "starrail" in reg._info
    info = reg._info["starrail"]
    assert info["manifest"]["name"] == "starrail"
    assert "starrail" in info["actions"]
    assert os.path.exists(os.path.join(info["path"], "driver.py"))


def test_smoke_registry_end_to_end_ping(src_dir, monkeypatch):
    """通过真实注册表启动 starrail 驱动子进程并执行 ping（完整链路）。"""
    import importlib
    reg_mod = importlib.import_module("smartplaybuddy.drivers.registry")

    old = os.environ.get("PYTHONPATH", "")
    monkeypatch.setenv("PYTHONPATH", src_dir + os.pathsep + old)

    # 冷启动导入较慢，放宽 ready 等待时间
    def _recv_long(self):
        try:
            return self._resp_queue.get(timeout=60)
        except queue.Empty:
            return None

    monkeypatch.setattr(reg_mod.DriverProcess, "_recv", _recv_long)

    reg = reg_mod.DriverRegistry()
    try:
        reg.scan()
        dd = reg_mod.DriversDict(reg)
        resp = dd["starrail"]({"operate": "ping"})
        assert resp["status"] == "ok"
        assert resp["result"]["pong"] is True
        assert resp["result"]["driver"] == "starrail"
    finally:
        reg.shutdown()


def test_smoke_host_subprocess_ready_ping_stop(driver_plugin_dir, src_dir):
    """直接启动驱动子进程（python -m smartplaybuddy.client --driver-host ...），
    验证 ready → operate(ping) → stop 完整 IPC 流程。"""
    env = dict(os.environ)
    env["PYTHONPATH"] = src_dir + os.pathsep + env.get("PYTHONPATH", "")

    cmd = [
        sys.executable, "-m", "smartplaybuddy.client", "--driver-host",
        os.path.join(driver_plugin_dir, "driver.py"),
    ]
    proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, env=env,
    )
    try:
        # 1. 就绪信号
        msg, _ = _recv_frame(proc.stdout)
        assert msg is not None, "驱动子进程未发送 ready 信号"
        assert msg.get("status") == "ready"

        # 2. operate ping
        _send_frame(proc.stdin, {"command": "operate", "cmd": "starrail", "params": {"operate": "ping"}})
        resp, _ = _recv_frame(proc.stdout)
        assert resp is not None and resp.get("status") == "ok", resp
        assert resp["result"]["pong"] is True

        # 3. operate status（不触碰游戏窗口）
        _send_frame(proc.stdin, {"command": "operate", "cmd": "starrail", "params": {"operate": "status"}})
        resp, _ = _recv_frame(proc.stdout)
        assert resp is not None and resp.get("status") == "ok", resp
        assert resp["result"]["driver"] == "starrail"

        # 4. 未知操作 → error
        _send_frame(proc.stdin, {"command": "operate", "cmd": "starrail", "params": {"operate": "nope"}})
        resp, _ = _recv_frame(proc.stdout)
        assert resp["status"] == "error"

        # 5. stop
        _send_frame(proc.stdin, {"command": "stop"})
        proc.wait(timeout=15)
        assert proc.poll() is not None
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        err = proc.stderr.read().decode("utf-8", errors="replace")
        assert "Traceback" not in err, f"驱动子进程 stderr 出现异常:\n{err}"


def test_smoke_mod_driver_mapping_consistent(driver_plugin_dir):
    """Mod 的任务 id → 操作映射 必须与驱动内 daily_task_dict 的任务 id 集合一致。"""
    import module.daily_task.DailyTask as dt_mod
    from mods.starrail import DAILY_TASK_OPS

    driver_task_ids = set(dt_mod.daily_task_dict.keys())
    assert set(DAILY_TASK_OPS.keys()) == driver_task_ids
    assert driver_task_ids == {2, 9, 10}


def test_smoke_mod_imports_and_protocol_objects():
    """Mod 可导入，且消息协议对象可正常序列化（不经网络）。"""
    from mods.starrail import StarRailMod, execute_starrail_flow
    from smartplaybuddy.ws.message import Message

    msg = Message(Type="command", Action="starrail", From="mod:1:ctrl",
                  RequestID="smoke-1", Data={"operate": "ping", "params": {}})
    payload = msg.to_json()
    d = json.loads(payload)
    assert d["type"] == "command"
    assert d["action"] == "starrail"
    decoded = json.loads(base64.b64decode(d["data"]))
    assert decoded["operate"] == "ping"

    assert callable(execute_starrail_flow)
    assert StarRailMod.name == "starrail"
