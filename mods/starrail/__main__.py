"""
星穹铁道自动化 Mod 启动入口。

用法（在项目根目录）：
    python -m mods.starrail --target-client my-pc
    python -m mods.starrail --target-client my-pc --user-id 123 --timeout 300
"""

import argparse
import asyncio
import base64
import json
import os
import platform
import sys

# 确保优先使用本仓库（src/）的 smartplaybuddy：
# 环境中可能残留其它 editable 安装（如旧版 SmartBuddy04 的 .pth），
# 会让 `import smartplaybuddy` 命中旧代码（缺少新翻译键 / 新驱动等）。
_WS_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SRC_DIR = os.path.join(_WS_ROOT, "src")
if os.path.isdir(_SRC_DIR) and _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from smartplaybuddy import config as app_config
from smartplaybuddy import log
from smartplaybuddy import user
from smartplaybuddy.config import WS_URL
from .mod import StarRailMod

logger = log.logger.getChild("Mod").getChild("StarRail").getChild("Entry")


def decode_user_id(access_token: str):
    """从 JWT access_token 的 payload 中解析 userId（尝试常见字段名）。"""
    if not access_token:
        return None
    try:
        payload = access_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
        for key in ("sub", "userId", "uid", "id", "user_id"):
            if data.get(key):
                return str(data[key])
    except Exception as e:
        logger.warning(f"解析 JWT userId 失败: {e}")
    return None


def main():
    parser = argparse.ArgumentParser(description="崩坏：星穹铁道 自动化 Mod")
    parser.add_argument("--target-client", default=None, help="目标设备名（client 端 deviceName）")
    parser.add_argument("--user-id", default=None, help="用户 ID（缺省时从 JWT 自动解析）")
    parser.add_argument("--device-name", default="starrail", help="Mod 自身注册的设备名（默认 starrail）")
    parser.add_argument("--timeout", type=float, default=180.0, help="单次驱动操作超时（秒）")
    args = parser.parse_args()

    async def start():
        tokens = user.refresh_login() or user.login()
        user.save_tokens(tokens)

        uid = args.user_id or decode_user_id(tokens.access_token)
        if not uid:
            logger.warning("未能解析 userId，指令分发时需传入完整 target_client (client:123:pc)")

        config = {
            "url": WS_URL,
            "headers": {"Authorization": f"Bearer {tokens.access_token}"},
            "status": {
                "device": {
                    "type": "mod",
                    "deviceName": args.device_name,
                    "deviceInfo": "StarRail automation mod (daily_task / physical_power)",
                    "platform": platform.platform(),
                    "machine": platform.machine(),
                    "appVersion": app_config.VERSION,
                }
            },
            "target_client": args.target_client,
            "user_id": uid,
            "default_timeout": args.timeout,
        }
        logger.info(f"StarRailMod 启动: target_client={args.target_client}, user_id={uid}")
        StarRailMod(**config)
        while True:
            await asyncio.sleep(1)

    try:
        asyncio.run(start())
    except KeyboardInterrupt:
        logger.info("starrail mod 已退出")


if __name__ == "__main__":
    main()
