"""
pytest 全局配置。

关键点：
1. 本工作区（SmartBuddy05）的 src/ 必须优先于环境中 SmartBuddy04 的 editable 安装，
   否则 `import smartplaybuddy` 会命中旧项目。
2. 将 starrail 驱动插件根目录加入 sys.path，使测试可 `import module.*` / `import utils.*`
   （与驱动子进程内的导入方式一致）。
"""
import os
import sys

WORKSPACE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(WORKSPACE, "src")
MODS_DIR = os.path.join(WORKSPACE, "mods")
DRIVER_PLUGIN = os.path.join(SRC, "smartplaybuddy", "drivers", "starrail")


def _ensure_path(p):
    # 始终将工作区路径移到 sys.path 最前——环境中可能同时存在 SmartBuddy04/05 的
    # editable 安装（.pth），仅做"不在则插入"会让旧项目（index 更靠前）抢先。
    if p in sys.path:
        sys.path.remove(p)
    sys.path.insert(0, p)


# 优先级：SRC 最先，其次 MODS_DIR，再其次插件根目录与 smartplaybuddy 包目录
_ensure_path(SRC)
_ensure_path(MODS_DIR)
_ensure_path(DRIVER_PLUGIN)
_ensure_path(os.path.join(SRC, "smartplaybuddy"))

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def workspace() -> str:
    return WORKSPACE


@pytest.fixture(scope="session")
def src_dir() -> str:
    return SRC


@pytest.fixture(scope="session")
def mods_dir() -> str:
    return MODS_DIR


@pytest.fixture(scope="session")
def driver_plugin_dir() -> str:
    return DRIVER_PLUGIN


@pytest.fixture(scope="session")
def starrail_driver_module(driver_plugin_dir, src_dir):
    """加载 drivers/starrail/driver.py（与 host.py 相同的方式），返回模块对象。

    加载后即可直接实例化 StarRailDriver 并调用 operate()。
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "starrail_driver_under_test",
        os.path.join(driver_plugin_dir, "driver.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
