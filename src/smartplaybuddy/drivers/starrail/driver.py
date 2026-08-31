"""
崩坏：星穹铁道 自动化驱动 (StarRail Driver)。

在 SmartPlayBuddy 驱动框架下，保留 starrail_assistant 的原始项目结构：
    drivers/starrail/
    ├── manifest.json          ← 驱动插件清单
    ├── driver.py              ← StarRailDriver（本文件，继承 BaseDriver）
    ├── requirements.txt       ← 第三方依赖声明
    ├── module/                ← 迁移自 starrail_assistant/module
    │   ├── common/            ←   截图/定位/启动游戏等通用工具
    │   ├── daily_task/        ←   每日实训任务（执行 + OCR 分析）
    │   ├── interface/         ←   界面管理（wait_until / wait_and_click）
    │   └── physical_power/    ←   开拓力清除 + OCR 识别
    ├── utils/log/             ← 迁移自 starrail_assistant/utils/log
    └── assets/                ← 迁移自 starrail_assistant/assets（图片 + JSON 配置）

对外通过 operate(command="starrail", params={"operate": ...}) 提供业务操作，
与 mods/starrail（StarRailMod）配合完成「日常任务」与「开拓力清理」自动化流程。
"""

import os
import sys


def _install_stdout_shim():
    """屏蔽游戏自动化模块的 print 输出，避免文本污染子进程 stdout 的二进制 IPC 帧通道。

    host.py 在 exec_module 之后才捕获 sys.stdout.buffer 用于写帧，
    因此这里保留原始 buffer 引用，仅丢弃文本层 write。
    仅在以驱动子进程方式运行时（--driver-host）启用。
    """
    original = sys.stdout

    class _StdoutShim:
        buffer = original.buffer
        encoding = getattr(original, "encoding", "utf-8")

        def write(self, *args, **kwargs):
            return 0

        def flush(self):
            pass

        def isatty(self):
            return False

        def fileno(self):
            return self.buffer.fileno()

        def __getattr__(self, name):
            return getattr(original, name)

    sys.stdout = _StdoutShim()


# 仅驱动子进程（--driver-host）时静默 print；本地调试时保持正常输出
if len(sys.argv) > 1 and sys.argv[1] == "--driver-host":
    _install_stdout_shim()

# 将插件根目录加入 sys.path，保持 module/、utils/ 等原始导入方式不变
_PLUGIN_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, _PLUGIN_ROOT)

# 供 `from drivers.base import BaseDriver` 解析。
# 驱动子进程运行时由 host.py 注入 smartplaybuddy 包目录；本地直接调试时自行注入。
_DRIVERS_PARENT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _DRIVERS_PARENT not in sys.path:
    sys.path.insert(0, _DRIVERS_PARENT)

from drivers.base import BaseDriver  # noqa: E402

from module.daily_task.DailyTask import (  # noqa: E402
    start_daily_task,
    observe_task,
    entrust,
    once_mix,
    take_photo,
    re_award,
)
from module.physical_power.PhysicalPower import clear_physical_power, get_power_data  # noqa: E402
from module.common.AutoOpen import StarRailGameManager  # noqa: E402


class StarRailDriver(BaseDriver):
    """崩坏：星穹铁道 业务驱动。

    每个 operate 均为一次可独立执行的游戏内操作；高阶编排（观察→逐项执行→领奖、
    查询体力→决策→清理）由 mods/starrail 中的 StarRailMod 负责。
    """

    name = "starrail"
    versionCode = "1.0.0"
    versionName = "v1.0.0"
    description = "崩坏：星穹铁道 日常任务 / 开拓力自动化驱动"

    def __init__(self):
        self.game = StarRailGameManager()

    def start(self):
        pass

    def stop(self):
        pass

    def operate(self, command: str, params: dict):
        if command != self.name:
            return {"status": "error", "message": f"unsupported command: {command}"}
        op = (params or {}).get("operate")

        # ---------- 健康检查 ----------
        if op == "ping":
            return {"status": "ok", "result": {"pong": True, "driver": self.name, "version": self.versionName}}
        if op == "status":
            return self._status()

        # ---------- 游戏生命周期 ----------
        if op == "game/running":
            return {"status": "ok", "result": {"running": bool(self.game.is_game_running())}}
        if op == "game/open":
            wait_for_login = bool(params.get("wait_for_login", True))
            opened = self.game.open_game(wait_for_login=wait_for_login)
            return {"status": "ok", "result": {"opened": bool(opened)}}
        if op == "game/switch":
            switched = self.game.switch_to_game()
            return {"status": "ok", "result": {"switched": bool(switched)}}
        if op == "game/close":
            closed = self.game.close_game()
            return {"status": "ok", "result": {"closed": bool(closed)}}

        # ---------- 每日实训任务 ----------
        if op == "daily_task/start":
            # 完整流程：观察 → 逐项执行 → 领取奖励（保留原始 start_daily_task 语义）
            start_daily_task()
            return {"status": "ok", "result": {"started": True}}
        if op == "daily_task/observe":
            task_ids = observe_task() or []
            return {"status": "ok", "result": {"task_ids": list(task_ids)}}
        if op == "daily_task/entrust":
            entrust()
            return {"status": "ok", "result": {"done": True, "op": "entrust"}}
        if op == "daily_task/mix":
            once_mix()
            return {"status": "ok", "result": {"done": True, "op": "mix"}}
        if op == "daily_task/photo":
            take_photo()
            return {"status": "ok", "result": {"done": True, "op": "photo"}}
        if op == "daily_task/reward":
            re_award()
            return {"status": "ok", "result": {"done": True, "op": "reward"}}

        # ---------- 开拓力 ----------
        if op == "power/query":
            data = get_power_data()
            return {"status": "ok", "result": data}
        if op == "power/clear":
            power_num = int(params.get("power_num", 0))          # 0 = 全部清完
            selection = int(params.get("selection", 3))          # 1信用点 2角色经验 3光锥经验
            use_reserve = bool(params.get("use_reserve", False))  # 是否使用后备开拓力
            clear_physical_power(power_num=power_num, selection=selection, use_reserve=use_reserve)
            return {
                "status": "ok",
                "result": {
                    "started": True,
                    "params": {"power_num": power_num, "selection": selection, "use_reserve": use_reserve},
                },
            }

        return {"status": "error", "message": f"unknown operate: {op}"}

    # ------------------------------------------------------------------
    def _status(self) -> dict:
        try:
            running = bool(self.game.is_game_running())
        except Exception:
            running = False
        return {
            "status": "ok",
            "result": {
                "driver": self.name,
                "version": self.versionName,
                "game_running": running,
                "modules": {
                    "daily_task": True,
                    "physical_power": True,
                    "auto_open": True,
                },
            },
        }


if __name__ == "__main__":
    # 本地调试入口：
    #   python driver.py ping
    #   python driver.py power/clear '{"power_num": 10, "selection": 3}'
    #   python driver.py daily_task/observe
    import json
    import sys as _sys

    # 兼容 GBK 等旧控制台编码：自动降级，避免 ✓/✗ 等字符 print 报错
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    _d = StarRailDriver()
    _op = _sys.argv[1] if len(_sys.argv) > 1 else "ping"
    _params = {}
    if len(_sys.argv) > 2:
        try:
            _params = json.loads(_sys.argv[2])
        except Exception as e:
            print(f"参数 JSON 解析失败: {e}")
            _sys.exit(1)

    if _op == "power/clear" and "power_num" not in _params:
        print('⚠ 警告: power/clear 未指定 power_num，将清空全部体力！建议先传 {"power_num": 10} 测试单场战斗。')
    _params.setdefault("operate", _op)
    print(json.dumps(_d.operate("starrail", _params), ensure_ascii=False, indent=2))
