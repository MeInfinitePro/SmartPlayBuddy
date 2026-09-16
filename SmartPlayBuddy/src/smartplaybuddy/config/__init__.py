"""
全局配置。集中管理服务地址、版本号等常量。

分层读取（优先级从高到低，12-Factor 风格）：
1. 环境变量：SPB_SERVER_HOST / SPB_WS_URL / SPB_VERSION
2. .env 文件：仅项目根 .env（deploy/.env 是 docker compose 用的模板，
   曾经因 pydantic-settings 元组"后者优先"覆盖根 .env，导致 mod 静默连错端点，勿再加入）
3. 代码内默认值（以下默认值即当前生产环境指向，本地开发可用环境变量覆盖）

对外 API 保持不变：其他模块仍 `from smartplaybuddy.config import SERVER_HOST, WS_URL, VERSION`。
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SPB_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    SERVER_HOST: str = "http://smtplay.cabyss.cn:8000"
    WS_URL: str = "ws://smtplay.cabyss.cn:2508/ws"
    VERSION: str = "v0.0.1"


settings = Settings()

# 兼容层：保持原有模块级常量 API
SERVER_HOST = settings.SERVER_HOST
WS_URL = settings.WS_URL
VERSION = settings.VERSION
