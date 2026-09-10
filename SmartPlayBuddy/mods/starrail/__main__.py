"""
星穹铁道自动化 Mod 启动入口。

用法（在项目根目录）：
    # 同机部署：client 与 Mod 在同一台电脑时，两端自动用主机名对齐，可省略参数
    python -m mods.starrail
    # 跨机 / 自定义设备名：显式指定目标 client 注册的 deviceName（或完整 client:{uid}:{name}）
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
from smartplaybuddy.device import resolve_device_name
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
    parser.add_argument("--target-client", default=None,
                        help="目标设备名（client 注册的 deviceName；缺省回退 SMTPLAY_DEVICE_NAME/本机主机名，"
                             "同机部署时自动与 client 对齐；也可传完整标识 client:{userId}:{deviceName}）")
    parser.add_argument("--user-id", default=None, help="用户 ID（缺省时从 JWT 自动解析）")
    parser.add_argument("--device-name", default="starrail", help="Mod 自身注册的设备名（默认 starrail）")
    # 默认 3600s：清体力（多场战斗）与完整日常可长达几十分钟，
    # 若沿用短超时（如 180s）会在驱动真正完成前被判超时，导致"执行完但无结果返回"。
    parser.add_argument("--timeout", type=float, default=3600.0, help="单次驱动操作超时（秒）")
    args = parser.parse_args()

    async def start():
        tokens = user.refresh_login() or user.login()
        user.save_tokens(tokens)

        uid = args.user_id or decode_user_id(tokens.access_token)
        if not uid:
            logger.warning("未能解析 userId，指令分发时需传入完整 target_client (client:123:pc)")

        # 目标设备解析：显式 --target-client > SMTPLAY_DEVICE_NAME > 主机名。
        # 与 client 端注册逻辑共用 device.resolve_device_name()，保证同机部署两端自动对齐。
        target_client = args.target_client or resolve_device_name()
        if not args.target_client:
            logger.info("未显式指定 --target-client，自动使用设备名 %s（请确认 client 端注册同名）", target_client)

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
            "target_client": target_client,
            "user_id": uid,
            "default_timeout": args.timeout,
        }
        logger.info(f"StarRailMod 启动: target_client={target_client}, user_id={uid}")
        StarRailMod(**config)
        while True:
            await asyncio.sleep(1)

    try:
        asyncio.run(start())
    except KeyboardInterrupt:
        logger.info("starrail mod 已退出")


if __name__ == "__main__":
    main()
