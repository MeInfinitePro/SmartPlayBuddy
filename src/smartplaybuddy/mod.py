"""
Mod 开发入口模块。
提供 Mod 基类供第三方开发者继承，实现自定义消息处理逻辑。
"""
from . import ws
from . import i18n
from . import log
from .config import WS_URL

import asyncio

logger = log.logger.getChild("Mod")

class Mod(ws.Connector):
    """Mod 基类，开发者继承并实现 main() 方法处理消息。"""

    def __init__(self, **config):
        super().__init__(**config)

    async def main(self, msg) -> None:
        print(msg)


def main(mod: type[Mod] = Mod):
    """Mod 启动入口。"""
    async def start():
        from . import config
        from . import user
        from .device import resolve_device_name
        from .ws.connector import CLOSE_CODE_TOKEN_REVOKED

        import platform

        # 外层循环：令牌临期/连接断开时重建连接（与 client.py、mods/starrail 同款）。
        # ensure_tokens（移植自上游）：令牌仍有效则复用，过期则 refresh，
        # 失败则重新走浏览器登录；force_login 用于 4001 token 吊销场景。
        TOKEN_TTL = 899
        RENEW_AT = TOKEN_TTL - 120
        CHECK_INTERVAL = 15
        force_login = False

        # 设备名解析：显式环境变量 SMTPLAY_DEVICE_NAME > 本机主机名兜底。
        # 空串会被服务端分配随机 UUID，外部无法按名定位。
        device_name = resolve_device_name()
        logger.info(i18n.translate("client.device_name_auto", name=device_name))

        while True:
            try:
                tokens = await user.ensure_tokens(force_login=force_login)
            except Exception as e:
                logger.warning("获取登录令牌失败：%s；%ds 后重试", e, CHECK_INTERVAL)
                await asyncio.sleep(CHECK_INTERVAL)
                continue
            user.save_tokens(tokens)
            force_login = False

            mod_config = {
                "url": WS_URL,
                "headers": {
                    # 新契约：WS 握手认证经 Cookie 传递（Bearer 保留兼容旧服务端）
                    "Authorization": f"Bearer {tokens.access_token}",
                    "Cookie": f"{user.ACCESS_COOKIE_NAME}={tokens.access_token}",
                },
                "status": {
                    "device": {
                        "type": "mod",
                        "deviceName": device_name,
                        "deviceInfo": "",
                        "platform": platform.platform(),
                        "machine": platform.machine(),
                        "appVersion": config.VERSION,
                    }
                }
            }
            m = mod(**mod_config)

            started = asyncio.get_event_loop().time()
            while True:
                await asyncio.sleep(CHECK_INTERVAL)
                if m._closed.is_set():
                    logger.warning("WS 连接已断开，%ds 后重连", CHECK_INTERVAL)
                    break
                elapsed = asyncio.get_event_loop().time() - started
                if elapsed >= RENEW_AT:
                    logger.info("access_token 即将过期（%ds），主动重建连接续期", TOKEN_TTL)
                    break

            try:
                await m.conn.close()
            except Exception:
                pass
            m.on_close()
            # 4001 = token 被吊销(他处登出)，下一轮直接重新登录
            force_login = (getattr(m, "close_code", None) == CLOSE_CODE_TOKEN_REVOKED)
            if force_login:
                logger.warning("连接因 token 被吊销(4001)断开，下一轮将重新登录")
            await asyncio.sleep(CHECK_INTERVAL)

    try:
        asyncio.run(start())
    except:
        logger.info(i18n.translate("system.close"))
