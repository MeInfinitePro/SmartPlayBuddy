"""
星穹铁道 Mod 指令测试控制器。

向运行中的 starrail Mod（mod:{userId}:starrail）发送一条指令并打印响应，
用于在游戏内验证完整链路：控制器 → Mod 编排 → 客户端 starrail 驱动 → 游戏。

用法（项目根目录）：
    # 先启动客户端（游戏所在电脑）与 Mod：
    #   smtplay                                     （或 python -m smartplaybuddy.client）
    #   python -m mods.starrail                     （同机部署自动对齐设备名，无需 --target-client）
    #
    # 再发指令：
    python -m mods.starrail.controller --operate status
    python -m mods.starrail.controller --operate game/running
    python -m mods.starrail.controller --operate game/open
    python -m mods.starrail.controller --operate daily_task
    python -m mods.starrail.controller --operate clear_power --param '{"power_num": 10}'
    python -m mods.starrail.controller --operate ping --to "mod:123:starrail"

参数：
    --operate        指令名（必填）：ping / status / game/running / game/open /
                    daily_task / daily_task/reward / power/query / clear_power
                    （daily_task 与 clear_power 执行前会先检查游戏已启动，未启动直接返回错误）
    --param          指令参数 JSON（可选，默认 {}）
    --target-client  目标设备名，会注入 params.target_client 供 Mod 分发（可选）
    --to             完整目标标识（默认 mod:{userId}:starrail）
    --timeout        等待响应超时秒数（默认 600，日常/清体力流程可能较久）
"""

import argparse
import asyncio
import base64
import json
import os
import platform
import sys
import time

# 确保优先使用本仓库（src/）的 smartplaybuddy（同 __main__.py 的处理）
_WS_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SRC_DIR = os.path.join(_WS_ROOT, "src")
if os.path.isdir(_SRC_DIR) and _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from smartplaybuddy import config as app_config
from smartplaybuddy import log
from smartplaybuddy import user
from smartplaybuddy.config import WS_URL
from smartplaybuddy.ws import Connector
from smartplaybuddy.ws.message import Message

from .__main__ import decode_user_id

logger = log.logger.getChild("Mod").getChild("StarRail").getChild("Controller")


class StarRailController(Connector):
    """连接一次，向 starrail Mod 发送单条指令，收到响应后关闭连接。"""

    def __init__(self, target, operate, params, timeout=600.0, **config):
        self.target = target
        self.operate = operate
        self.params = params
        self.timeout = timeout
        self._request_id = f"starrail-ctl-{int(time.time() * 1000)}"
        self._response = None
        self._done = asyncio.Event()
        super().__init__(**config)

    async def main(self, msg) -> None:
        # 其他消息忽略（本控制器只关心自己的响应）
        logger.debug("收到无关消息: type=%s action=%s", msg.Type, msg.Action)

    def on_close(self):
        # 连接结束（含连接失败）时兜底唤醒等待方
        if self._response is None:
            self._response = {"type": "closed", "data": None}
        self._done.set()

    async def loop(self):
        """覆写消息循环：先发指令，再等待匹配 requestId 的响应。"""
        try:
            await self.conn.send(
                self.Message(
                    Type="command",
                    Action="starrail",
                    To=self.target,
                    RequestID=self._request_id,
                    Data={"operate": self.operate, "params": self.params},
                ).to_json()
            )
            logger.info("已发送指令 %s → %s", self.operate, self.target)

            deadline = time.time() + self.timeout
            while time.time() < deadline:
                try:
                    raw = await asyncio.wait_for(self.conn.recv(), timeout=deadline - time.time())
                except asyncio.TimeoutError:
                    logger.error("等待响应超时（%.0fs）", self.timeout)
                    self._response = {"type": "timeout", "data": None}
                    self._done.set()
                    break
                except Exception as e:
                    logger.error("接收消息失败: %s", e)
                    break

                if isinstance(raw, bytes):
                    continue  # 本场景响应不含二进制帧

                try:
                    d = json.loads(raw)
                    msg = self.Message.from_json(d)
                except Exception as e:
                    logger.error("消息解析失败: %s", e)
                    continue

                if msg.Type in ("response", "error") and msg.RequestID == self._request_id:
                    self._response = {"type": msg.Type, "data": msg.Data}
                    self._done.set()
                    break
                await self.main(msg)
        finally:
            try:
                await self.conn.close()
            except Exception:
                pass


def main():
    parser = argparse.ArgumentParser(description="星穹铁道 Mod 指令测试控制器")
    parser.add_argument("--operate", required=True,
                        help="ping / status / game/running / game/open / daily_task / daily_task/reward / power/query / clear_power")
    parser.add_argument("--param", default="{}", help="指令参数 JSON，例如 '{\"power_num\": 10}'")
    parser.add_argument("--target-client", default=None, help="目标客户端设备名（注入 params.target_client）")
    parser.add_argument("--to", default=None, help="完整目标标识，默认 mod:{userId}:starrail")
    parser.add_argument("--timeout", type=float, default=3600.0, help="等待响应超时（秒）")
    args = parser.parse_args()

    try:
        params = json.loads(args.param or "{}")
        if not isinstance(params, dict):
            raise ValueError("--param 必须是 JSON 对象")
    except ValueError as e:
        parser.error(f"--param 解析失败: {e}")
    # 让 Mod 内部 dispatch 也使用相同超时（长操作如 clear_power 可能跑几十分钟）
    params.setdefault("timeout", args.timeout)

    async def start():
        tokens = user.refresh_login() or user.login()
        user.save_tokens(tokens)
        uid = decode_user_id(tokens.access_token)
        if args.target_client:
            params.setdefault("target_client", args.target_client)
        target = args.to or f"mod:{uid}:starrail"

        config = {
            "url": WS_URL,
            "headers": {"Authorization": f"Bearer {tokens.access_token}"},
            "status": {
                "device": {
                    "type": "mod",
                    "deviceName": "starrail-controller",
                    "deviceInfo": "StarRail test controller",
                    "platform": platform.platform(),
                    "machine": platform.machine(),
                    "appVersion": app_config.VERSION,
                }
            },
        }
        ctl = StarRailController(target, args.operate, params, timeout=args.timeout, **config)
        try:
            await asyncio.wait_for(ctl._done.wait(), timeout=args.timeout + 10)
        except asyncio.TimeoutError:
            ctl._response = {"type": "timeout", "data": None}
        print(json.dumps(ctl._response, ensure_ascii=False, indent=2))

    try:
        asyncio.run(start())
    except KeyboardInterrupt:
        logger.info("控制器已退出")


if __name__ == "__main__":
    main()
