"""崩坏：星穹铁道 自动化 Mod 包。

导入前先校正 smartplaybuddy 的解析路径（环境里可能有多个 editable 安装）。
"""
import os
import sys

_WS_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SRC_DIR = os.path.join(_WS_ROOT, "src")
if os.path.isdir(_SRC_DIR) and _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from .mod import StarRailMod, execute_starrail_flow, map_task_id_to_operate, DAILY_TASK_OPS  # noqa: E402

__all__ = ["StarRailMod", "execute_starrail_flow", "map_task_id_to_operate", "DAILY_TASK_OPS"]
