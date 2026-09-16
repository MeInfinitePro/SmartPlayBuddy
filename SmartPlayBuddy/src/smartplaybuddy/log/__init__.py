"""
日志模块。
配置根 logger：同时输出到控制台和按天轮转的日志文件。
"""
import logging
from logging.handlers import TimedRotatingFileHandler
import os
import importlib.util

# 日志格式
log_format = logging.Formatter("%(levelname)-8s|\t%(asctime)s\t%(name)-30s\t%(message)s")

# 控制台 Handler
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_format)

package = "smartplaybuddy"
logdir = "logs"

name = "SmtPlay"
level = logging.INFO
# level = logging.DEBUG

# 定位项目根目录（用于存放日志文件）
root_path = os.path.dirname(importlib.util.find_spec(package).submodule_search_locations[0])
if os.path.basename(root_path) == "src":
    root_path = os.path.dirname(root_path)

log_path = os.path.join(root_path, logdir)
if not os.path.exists(log_path):
    os.makedirs(log_path)

# 根 logger
logger = logging.getLogger(name)
logger.setLevel(level)
logger.addHandler(console_handler)

class SafeTimedRotatingFileHandler(TimedRotatingFileHandler):
    """Windows 兼容：client 与 mod 共写同一日志文件时，跨天滚动会因
    另一进程占用文件导致 os.rename 抛 PermissionError(WinError 32)，
    进而触发 logging error 刷屏。这里改为：滚动失败则跳过本轮滚动，
    继续写入原文件（日志功能不受影响，只是当天不做文件切分）。"""

    def doRollover(self):
        try:
            super().doRollover()
        except PermissionError:
            pass


# 文件 Handler（按天轮转，保留 30 天）
file_handler = SafeTimedRotatingFileHandler(f"{log_path}/{name}.log", encoding="utf-8", when="D", interval=1, backupCount=30)
file_handler.setFormatter(log_format)
logger.addHandler(file_handler)
