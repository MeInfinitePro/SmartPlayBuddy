import os
import subprocess
import json
import time
import string
from typing import Optional
from pathlib import Path

import psutil

try:
    import win32gui
    import win32con
    import win32process
    import win32api
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False

try:
    import pygetwindow as gw
    HAS_PYGETWINDOW = True
except ImportError:
    HAS_PYGETWINDOW = False

import module.interface.InterfaceManager as interface


class StarRailGameManager:
    """崩坏：星穹铁道游戏管理器 - 整合启动、切换、关闭和界面操作"""

    # 类常量
    TARGET_WIDTH = 1920
    TARGET_HEIGHT = 1080
    PROCESS_NAMES = ["StarRail.exe", "崩坏星穹铁道.exe", "HonkaiStarRail.exe"]
    PRIORITY_DRIVES = ['D:', 'E:', 'C:']

    def __init__(self, cache_file: str = "starrail_config.json"):
        # 路径设置
        self.base_path = Path(__file__).resolve().parent.parent.parent
        self.assets_path = self.base_path / "assets"
        self.image_path = self.assets_path / "images"
        self.common_img_path = self.image_path / "common"
        self.json_path = self.base_path / "assets" / "json"
        self.json_path.mkdir(parents=True, exist_ok=True)

        # 缓存文件
        self.cache_file = self.json_path / cache_file
        self.config = self._load_config()
        self.game_exe_path = self.config.get("game_path")
        self.game_process = None
        self.is_opened = False

    # ==================== 配置管理 ====================

    def _load_config(self) -> dict:
        """加载配置文件"""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    print(f"✓ 加载配置文件: {self.cache_file}")
                    return config
            except Exception as e:
                print(f"加载配置文件失败: {e}")
        else:
            print("未找到配置文件，将进行首次搜索")
        return {}

    def _save_config(self) -> None:
        """保存配置文件"""
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
            print(f"✓ 配置已保存: {self.cache_file}")
        except Exception as e:
            print(f"保存配置失败: {e}")

    def clear_cache(self) -> None:
        """清除缓存"""
        if self.cache_file.exists():
            self.cache_file.unlink()
            print(f"✓ 已清除缓存: {self.cache_file}")
        self.game_exe_path = None
        self.config = {}

    # ==================== 游戏路径搜索 ====================

    def _search_game_on_drive(self, drive: str) -> Optional[str]:
        """在指定磁盘搜索 StarRail.exe"""
        print(f"正在搜索 {drive} 盘...")
        search_paths = [
            drive,
            f"{drive}\\",
            f"{drive}\\Star Rail",
            f"{drive}\\Games\\Star Rail",
            f"{drive}\\Program Files\\Star Rail",
            f"{drive}\\Program Files (x86)\\Star Rail",
        ]

        for search_path in search_paths:
            if not os.path.exists(search_path):
                continue

            try:
                for root, dirs, files in os.walk(search_path):
                    depth = root.replace(drive, "").count(os.sep)
                    if depth > 5:
                        del dirs[:]
                        continue

                    if 'StarRail.exe' in files:
                        exe_path = os.path.join(root, 'StarRail.exe')
                        print(f"✓ 找到游戏: {exe_path}")
                        return exe_path

                    if 'Game' in dirs and depth < 3:
                        game_path = os.path.join(root, 'Game', 'StarRail.exe')
                        if os.path.exists(game_path):
                            print(f"✓ 找到游戏: {game_path}")
                            return game_path
            except (PermissionError, OSError):
                continue
        return None

    def _full_disk_search(self) -> Optional[str]:
        """全盘搜索游戏路径"""
        print("=" * 60)
        print("首次启动，正在全盘搜索 StarRail.exe...")
        print("=" * 60)

        for drive in self.PRIORITY_DRIVES:
            if os.path.exists(drive):
                exe_path = self._search_game_on_drive(drive)
                if exe_path:
                    return exe_path

        for letter in string.ascii_uppercase:
            drive = f"{letter}:"
            if drive not in self.PRIORITY_DRIVES and os.path.exists(drive):
                exe_path = self._search_game_on_drive(drive)
                if exe_path:
                    return exe_path

        print("✗ 全盘搜索未找到 StarRail.exe")
        return None

    def get_game_path(self) -> Optional[str]:
        """获取游戏路径（优先使用缓存）"""
        if self.game_exe_path and os.path.exists(self.game_exe_path):
            print(f"✓ 使用缓存的路径: {self.game_exe_path}")
            return self.game_exe_path

        if self.game_exe_path and not os.path.exists(self.game_exe_path):
            print(f"⚠ 缓存的路径不存在: {self.game_exe_path}")
            print("将重新搜索...")

        exe_path = self._full_disk_search()
        if exe_path:
            self.game_exe_path = exe_path
            self.config['game_path'] = exe_path
            self._save_config()
            return exe_path
        return None

    # ==================== 游戏生命周期管理 ====================

    def launch_game(self, width: int = 1920, height: int = 1080,
                    fullscreen: bool = False, wait_for_window: bool = True) -> Optional[subprocess.Popen]:
        """启动游戏"""
        exe_path = self.get_game_path()
        if not exe_path:
            print("错误: 未找到游戏，请检查游戏是否已安装")
            return None

        if not os.path.exists(exe_path):
            print(f"错误: 游戏文件不存在 - {exe_path}")
            return None

        fullscreen_flag = "1" if fullscreen else "0"
        params = [
            exe_path,
            "-screen-fullscreen", fullscreen_flag,
            "-screen-width", str(width),
            "-screen-height", str(height)
        ]

        print("\n" + "=" * 60)
        print("启动游戏:")
        print(f"  程序: {exe_path}")
        print(f"  分辨率: {width}x{height}")
        print(f"  模式: {'全屏' if fullscreen else '窗口化/非全屏'}")
        print("=" * 60)

        try:
            self.game_process = subprocess.Popen(params)
            print(f"✓ 游戏进程已启动 (PID: {self.game_process.pid})")
            self.is_opened = True

            if wait_for_window:
                print("等待游戏窗口加载...")
                time.sleep(5)
                print("✓ 游戏窗口已加载")

            return self.game_process
        except Exception as e:
            print(f"启动失败: {e}")
            self.is_opened = False
            return None

    def close_game(self) -> bool:
        """关闭游戏"""
        print("正在关闭游戏...")
        closed = False

        if self.game_process:
            try:
                self.game_process.terminate()
                self.game_process.wait(timeout=5)
                print("✓ 游戏已关闭（通过进程对象）")
                closed = True
            except:
                pass

        if not closed:
            try:
                for proc in psutil.process_iter(['pid', 'name']):
                    if proc.info['name'] in self.PROCESS_NAMES:
                        proc.terminate()
                        proc.wait(timeout=5)
                        print("✓ 游戏已关闭（通过进程名）")
                        closed = True
                        break
            except Exception as e:
                print(f"关闭游戏时出错: {e}")

        if not closed:
            print("✗ 未找到运行中的游戏进程")

        self.game_process = None
        self.is_opened = False
        return closed

    def is_game_running(self) -> bool:
        """检查游戏是否正在运行"""
        for proc in psutil.process_iter(['name']):
            try:
                if proc.info['name'] in self.PROCESS_NAMES:
                    return True
            except:
                pass
        return False

    # ==================== 窗口管理 ====================

    def switch_to_game(self, force: bool = False) -> bool:
        """通过进程查找游戏窗口并切换到前台"""
        if not HAS_WIN32:
            print("请安装 pywin32: pip install pywin32")
            return False

        # 查找游戏进程PID
        target_pids = []
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                if proc.info['name'] in self.PROCESS_NAMES:
                    target_pids.append(proc.info['pid'])
            except:
                pass

        if not target_pids:
            print("✗ 未找到游戏进程")
            return False

        # 查找对应窗口
        def enum_callback(hwnd, hwnd_list):
            if win32gui.IsWindowVisible(hwnd) and win32gui.IsWindowEnabled(hwnd):
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if pid in target_pids:
                    hwnd_list.append(hwnd)
            return True

        windows = []
        win32gui.EnumWindows(enum_callback, windows)

        if not windows:
            print("✗ 未找到游戏窗口")
            return False

        hwnd = windows[0]
        title = win32gui.GetWindowText(hwnd)
        print(f"找到窗口: {title}")

        # 恢复并激活窗口
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            time.sleep(0.1)

        win32gui.SetForegroundWindow(hwnd)

        # 强制模式：模拟Alt键辅助激活
        if force:
            win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
            win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
            win32gui.SetForegroundWindow(hwnd)

        print("✓ 已切换到游戏窗口")
        return True

    def check_window_resolution(self) -> bool:
        """检查游戏客户区分辨率是否正确（使用 win32gui 获取客户区尺寸）"""
        if not HAS_WIN32:
            print("请安装 pywin32: pip install pywin32")
            return False

        # 查找游戏窗口
        target_pids = []
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                if proc.info['name'] in self.PROCESS_NAMES:
                    target_pids.append(proc.info['pid'])
            except:
                pass

        if not target_pids:
            print("未找到游戏进程")
            return False

        # 枚举窗口查找游戏窗口
        def enum_callback(hwnd, hwnd_list):
            if win32gui.IsWindowVisible(hwnd) and win32gui.IsWindowEnabled(hwnd):
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if pid in target_pids:
                    hwnd_list.append(hwnd)
            return True

        windows = []
        win32gui.EnumWindows(enum_callback, windows)

        if not windows:
            print("未找到游戏窗口")
            return False

        hwnd = windows[0]

        # 获取客户区尺寸（游戏画面实际尺寸）
        rect = win32gui.GetClientRect(hwnd)
        client_width = rect[2] - rect[0]
        client_height = rect[3] - rect[1]

        # 检查客户区尺寸是否匹配目标分辨率
        if client_width == self.TARGET_WIDTH and client_height == self.TARGET_HEIGHT:
            print(f"✓ 游戏客户区尺寸正确 ({client_width}x{client_height})")
            return True

        print(f"⚠ 客户区尺寸异常: {client_width}x{client_height}，期望: {self.TARGET_WIDTH}x{self.TARGET_HEIGHT}")
        return False
    def fix_window_and_restart(self) -> bool:
        """修复窗口问题（关闭后重启）"""
        print("正在修复窗口设置...")
        self.close_game()
        time.sleep(2)
        result = self.launch_game(
            width=self.TARGET_WIDTH,
            height=self.TARGET_HEIGHT,
            fullscreen=False
        )
        return result is not None

    # ==================== 核心接口：open_game ====================

    def open_game(self, wait_for_login: bool = False, login_timeout: float = 60.0) -> bool:
        """
        打开游戏（智能启动/切换）

        Args:
            wait_for_login: 是否等待登录界面
            login_timeout: 等待登录超时时间（秒）

        Returns:
            是否成功进入游戏
        """
        # 如果游戏已在运行，检查窗口并切换到前台
        if self.is_game_running():
            print("游戏已在运行，切换到前台...")
            self.switch_to_game()

            # 检查窗口分辨率是否正确
            if not self.check_window_resolution():
                print("窗口分辨率异常，重新启动游戏...")
                self.close_game()
                time.sleep(2)
                self.launch_game(
                    width=self.TARGET_WIDTH,
                    height=self.TARGET_HEIGHT,
                    fullscreen=False
                )
                time.sleep(5)
        else:
            # 游戏未运行，启动游戏
            print("游戏未运行，正在启动...")
            process = self.launch_game(
                width=self.TARGET_WIDTH,
                height=self.TARGET_HEIGHT,
                fullscreen=False,
                wait_for_window=True
            )
            if not process:
                print("✗ 游戏启动失败")
                return False

        return True

    # ==================== 兼容性接口 ====================

    def auto_open(self) -> None:
        """兼容旧接口"""
        self.open_game(wait_for_login=False)

    def check_and_fix_window(self) -> bool:
        """兼容旧接口"""
        if not self.check_window_resolution():
            return self.fix_window_and_restart()
        return True


# 使用示例
if __name__ == "__main__":
    # 安装依赖: pip install psutil pygetwindow pywin32
    game_manager = StarRailGameManager()
    game_manager.open_game()