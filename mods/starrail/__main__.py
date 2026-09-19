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
from smartplaybuddy.ws.connector import CLOSE_CODE_TOKEN_REVOKED
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
        # 外层重连循环：每次迭代 = 刷新令牌 → 建立连接 → 保活观察 → 断开重来。
        # 背景（2026-09-14 挂载实测）：access_token 仅 899s，过期后服务器会摘除会话
        # 但不断 TCP、不给任何通知（连接表现为"假在线"，指令全部 session not found）。
        # 因此在令牌过期前（780s）主动择机重建连接续期。
        TOKEN_TTL = 899
        RENEW_AT = TOKEN_TTL - 120        # 提前 2 分钟重建
        CHECK_INTERVAL = 15

        # 取令牌 / 建连接的失败重试退避（15s 起，最大 300s）
        RETRY_BASE = 15
        RETRY_MAX = 300
        backoff = RETRY_BASE
        force_login = False      # 上一轮连接因 4001(token 吊销)断开时，跳过 refresh 直接重登

        while True:
            # 背景（2026-09-15 14:32）：平台服务器短暂 502 时，refresh_login 与
            # 回退 login 会同时抛错；若不捕获，异常会冒泡出 asyncio.run() 直接结束
            # 整个 mod 进程（表现为"莫名其妙掉线、必须人工重启"）。
            # 因此这里所有暂态故障一律退避重试，进程始终保持存活。
            #
            # ensure_tokens（移植自上游）：令牌仍有效则复用（重连更快），
            # 过期则 refresh，refresh 失败或 force_login 则重新走浏览器登录。
            try:
                tokens = await user.ensure_tokens(force_login=force_login)
            except Exception as e:
                logger.warning("获取登录令牌失败：%s；%ds 后重试（进程保持存活）", e, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, RETRY_MAX)
                continue
            user.save_tokens(tokens)
            force_login = False

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
                # 新契约：WS 握手认证经 Cookie 传递（Bearer 保留兼容旧服务端）
                "headers": {"Authorization": f"Bearer {tokens.access_token}",
                            "Cookie": f"access_token={tokens.access_token}"},
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
            logger.info("StarRailMod 启动: deviceName=%s, target_client=%s, user_id=%s",
                    args.device_name, target_client, uid)
            try:
                mod = StarRailMod(**config)
            except Exception as e:
                logger.warning("建立 WS 连接失败：%s；%ds 后重试", e, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, RETRY_MAX)
                continue
            backoff = RETRY_BASE  # 连接成功，重置退避

            # 保活观察：连接被动断开，或令牌临期且当前空闲时，退出内层循环触发重连。
            # 另每 15s 比对 keyring 中的账号：本机重新登录切换账号后，立即重建连接换身份，
            # 不必等令牌续期周期（2026-09-19）。
            started = asyncio.get_running_loop().time()
            try:
                while True:
                    await asyncio.sleep(CHECK_INTERVAL)
                    if mod._closed.is_set():
                        logger.warning("WS 连接已断开，%ds 后重连", CHECK_INTERVAL)
                        break
                    try:
                        switched = user.login._load_tokens()
                        new_uid = decode_user_id(switched.access_token) if switched else None
                        if uid and new_uid and new_uid != uid:
                            logger.info("检测到本机登录账号已切换（%s -> %s），重建连接切换身份", uid, new_uid)
                            break
                    except Exception as e:
                        logger.debug("账号切换检查失败（忽略）：%s", e)
                    elapsed = asyncio.get_running_loop().time() - started
                    if elapsed >= RENEW_AT and not mod._tasks:
                        logger.info("access_token 即将过期（%ds），空闲中主动重建连接续期", TOKEN_TTL)
                        break
                    if elapsed >= RENEW_AT:
                        logger.info("令牌临期但有 %d 个指令执行中，延迟重建", len(mod._tasks))
            except Exception as e:
                # 保活期间任何异常（网络抖动等）都只触发重连，不结束进程
                logger.warning("保活循环异常：%s；%ds 后重连", e, CHECK_INTERVAL)

            try:
                await mod.conn.close()
            except Exception:
                pass
            mod.on_close()  # 幂等：置位 _closed、清空 pending
            # 记录断开原因：4001 = token 被吊销(他处登出)，refresh token 一并失效，
            # 下一轮 ensure_tokens 跳过 refresh 直接重新登录。
            force_login = (getattr(mod, "close_code", None) == CLOSE_CODE_TOKEN_REVOKED)
            if force_login:
                logger.warning("连接因 token 被吊销(4001)断开，下一轮将重新登录")
            await asyncio.sleep(CHECK_INTERVAL)

    try:
        asyncio.run(start())
    except KeyboardInterrupt:
        logger.info("starrail mod 已退出")


if __name__ == "__main__":
    main()
