"""
设备标识解析（client 注册 / mod 路由共用）。

两端必须走同一套规则，否则 mod 的 --target-client 与 client 实际注册的
deviceName 会对不上（表现为 driver/ping 等指令"等待客户端响应超时"）。

解析优先级（从高到低）：
    1. 显式传入的值（如 --target-client）
    2. 环境变量 SMTPLAY_DEVICE_NAME
    3. 本机主机名（兜底）

字符策略：设备名会进入路由标识 client:{userId}:{deviceName}（':' 是结构分隔符），
并出现在日志/会话索引里，因此只保留 ASCII 字母/数字/._-；中文等非 ASCII 字符
会被替换为 '-'。若提供的名字整体无法构成 ASCII（如全中文），视为无效并回退
主机名——同时打告警说明原值被忽略，避免"填了中文名却静默变成别的名字"。
强烈建议使用 ASCII 设备名（如 my-pc），或统一通过 SMTPLAY_DEVICE_NAME 指定。

主机名兜底的意义：即使完全不配置环境变量，client 也能注册成一个
固定、可预测、可路由的设备名（而不是空串被服务端分配随机 UUID）；
同机部署时 mod 用同一规则解析，天然与 client 对齐，无需手填 --target-client。
"""

import os
import re
import socket

from . import i18n
from . import log

logger = log.logger.getChild("Device")

ENV_DEVICE_NAME = "SMTPLAY_DEVICE_NAME"

# 路由标识 client:{userId}:{deviceName} 及日志/JSON 均需设备名保持"安全字符"
_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]")


def normalize_device_name(name) -> str:
    """清洗设备名：仅保留字母/数字/._-，其余字符替换为 '-'，并去掉首尾 '-'。

    注意：非 ASCII 字符（含中文）不在白名单内，会被替换/清空，
    不会原样出现在路由标识中。
    """
    if name is None:
        return ""
    cleaned = _SAFE_RE.sub("-", str(name).strip())
    return cleaned.strip("-")


def _fallback_hostname() -> str:
    """主机名兜底（去掉可能的域名后缀，如 my-pc.example.com → my-pc）。"""
    host = socket.gethostname().split(".")[0]
    name = normalize_device_name(host)
    if name:
        return name
    # 极端情况：主机名整体非 ASCII（如 Linux 中文主机名），无法构成 ASCII 名
    logger.warning(i18n.translate("device.hostname_fallback",
                                  name=host or "<empty>",
                                  env=ENV_DEVICE_NAME))
    return "smtplay-device"


def resolve_device_name(explicit=None) -> str:
    """解析稳定的设备名（非空）。

    Args:
        explicit: 显式指定的设备名；为 None 时依次回退
                  环境变量 SMTPLAY_DEVICE_NAME → 本机主机名。
    """
    raw = explicit if explicit is not None else os.environ.get(ENV_DEVICE_NAME)
    name = normalize_device_name(raw)
    if name:
        return name

    if raw and raw.strip():
        # 填了名字但清洗后为空（全中文/全特殊字符）：不能静默丢弃，需告警说明
        logger.warning(i18n.translate("device.non_ascii_name_ignored",
                                      name=str(raw).strip(),
                                      env=ENV_DEVICE_NAME))

    return _fallback_hostname()
