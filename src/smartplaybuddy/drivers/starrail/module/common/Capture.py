import time
import win32gui
import win32process
import psutil
import ctypes
from typing import Optional, Tuple, Dict
import numpy as np
import json
import os
from utils.log.Log import Log
# Windows API函数声明
user32 = ctypes.windll.user32
shcore = ctypes.windll.shcore
log=Log()

class WindowPositionManager:
    """窗口位置管理器，负责保存和加载窗口位置"""

    def __init__(self):
        self.json_path = os.path.join(os.path.dirname(__file__), '../../assets/json')
        self.config_file = os.path.join(self.json_path,"locate.json")
    def save_window_position(self, window_info: Dict) -> bool:
        """保存窗口位置到JSON文件"""
        try:
            # 准备要保存的数据
            position_data = {
                'title': window_info.get('title'),
                'class_name': window_info.get('class_name'),
                'rect': window_info.get('rect'),
                'width': window_info.get('width'),
                'height': window_info.get('height'),
            }
            # 读取现有数据（如果文件存在）
            existing_data = {}
            if os.path.exists(self.config_file):
                if os.path.getsize(self.config_file)!=0:
                    with open(self.config_file, 'r', encoding='utf-8') as f:
                        existing_data = json.load(f)


            # 更新数据
            existing_data['last_window_position'] = position_data
            # print(existing_data)
            # 保存到文件
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(existing_data, f, indent=4, ensure_ascii=False)
            return True

        except Exception as e:
            print(f"保存窗口位置时出错: {e}")

            return False

    def load_last_window_position(self) -> Optional[Dict]:
        """从JSON文件加载上次保存的窗口位置"""
        try:
            if not os.path.exists(self.config_file):
                print(f"配置文件不存在: {self.config_file}")
                return None

            with open(self.config_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            last_position = data.get('last_window_position')
            if last_position:
                return last_position
            else:
                print("配置文件中没有窗口位置信息")
                return None

        except Exception as e:
            print(f"加载窗口位置时出错: {e}")
            return None

    def compare_with_last_position(self, current_window_info: Dict) -> bool:
        """比较当前窗口位置与上次保存的位置是否相同"""
        last_position = self.load_last_window_position()

        if not last_position:
            return False

        current_rect = current_window_info.get('rect')
        last_rect = last_position.get('rect')

        if current_rect == last_rect:
            return True
        else:
            return False


def set_dpi_awareness():
    """设置进程的DPI感知能力，确保获取正确的窗口坐标"""
    try:
        if hasattr(shcore, 'SetProcessDpiAwareness'):
            result = shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
            if result == 0:
                return True
    except:
        pass

    try:
        if user32.SetProcessDPIAware():
            return True
    except:
        pass

    return False


def get_window_rect_accurate(hwnd: int) -> Tuple[int, int, int, int]:
    """获取准确的窗口位置和大小（排除阴影和边框影响）"""
    try:
        # 使用DwmGetWindowAttribute获取扩展框架边界（排除窗口阴影）
        from ctypes import Structure, byref

        class RECT(Structure):
            _fields_ = [
                ('left', ctypes.c_long),
                ('top', ctypes.c_long),
                ('right', ctypes.c_long),
                ('bottom', ctypes.c_long)
            ]

        DWMWA_EXTENDED_FRAME_BOUNDS = 9
        rect_ex = RECT()

        dwmapi = ctypes.windll.dwmapi
        if dwmapi.DwmGetWindowAttribute:
            result = dwmapi.DwmGetWindowAttribute(
                hwnd,
                DWMWA_EXTENDED_FRAME_BOUNDS,
                byref(rect_ex),
                ctypes.sizeof(rect_ex)
            )

            if result == 0:
                return (rect_ex.left, rect_ex.top, rect_ex.right, rect_ex.bottom)
    except:
        pass

    # 备用方法：使用GetWindowRect
    rect = win32gui.GetWindowRect(hwnd)
    return rect


def capture_window_screenshot(hwnd: int, save_path: Optional[str] = None):
    """截取指定窗口的屏幕截图"""
    try:
        from PIL import ImageGrab

        # 获取窗口的准确位置
        left, top, right, bottom = get_window_rect_accurate(hwnd)
        width = right - left
        height = bottom - top

        if width <= 0 or height <= 0:
            print(f"窗口尺寸无效: {width}x{height}")
            return None


        # 截取屏幕
        bbox = (left, top, right, bottom)
        screenshot = ImageGrab.grab(bbox=bbox, all_screens=True)

        # 转换为numpy数组
        img_array = np.array(screenshot)

        # 保存图片
        if save_path:
            screenshot.save(save_path)
            # print(f"截图已保存到: {save_path}")


    except Exception as e:
        print(f"截图时出错: {e}")
        return None


def get_starrail_main_window(save_position: bool = True, compare_position: bool = False) -> Optional[dict]:
    """获取星穹铁道主窗口信息

    Args:
        save_position: 是否保存窗口位置到locate.json
        compare_position: 是否与上次保存的位置进行比较
    """
    # 设置DPI感知
    set_dpi_awareness()

    # 初始化位置管理器
    position_manager = WindowPositionManager()

    # 查找StarRail.exe进程
    target_pid = None
    for proc in psutil.process_iter(['pid', 'name']):
        if proc.info['name'] == 'StarRail.exe':
            target_pid = proc.info['pid']
            break

    if target_pid is None:
        print("未找到StarRail.exe进程")
        return None

    print(f"找到StarRail.exe进程，PID: {target_pid}")

    # 查找主窗口
    main_hwnd = None
    main_window_info = None

    def enum_callback(hwnd, extra):
        nonlocal main_hwnd, main_window_info
        try:
            _, found_pid = win32process.GetWindowThreadProcessId(hwnd)
            if found_pid == target_pid and win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                class_name = win32gui.GetClassName(hwnd)

                # Unity游戏窗口特征
                if class_name in ['UnityWndClass', 'UnityFrame'] or (title and '星穹' in title):
                    rect = get_window_rect_accurate(hwnd)
                    width = rect[2] - rect[0]
                    height = rect[3] - rect[1]

                    # 选择最大的可见窗口作为主窗口
                    if main_hwnd is None or width * height > (main_window_info['width'] * main_window_info['height']):
                        main_hwnd = hwnd
                        main_window_info = {
                            'hwnd': hwnd,
                            'title': title,
                            'class_name': class_name,
                            'rect': rect,
                            'width': width,
                            'height': height
                        }
        except:
            pass
        return True

    win32gui.EnumWindows(enum_callback, None)

    if main_window_info:
        log.info("找到主窗口:")
        log.info("  标题: {main_window_info['title']}")
        log.info("  尺寸: {main_window_info['width']}x{main_window_info['height']}")

        # 保存窗口位置到locate.json
        if save_position:
            position_manager.save_window_position(main_window_info)

        # 与上次保存的位置进行比较
        if compare_position:
            position_manager.compare_with_last_position(main_window_info)

        return main_window_info
    else:
        print("未找到游戏主窗口")
        return None


def screen_capture(save_path: Optional[str] = os.path.join(os.path.dirname(__file__),"data","screenshot.png"), save_position: bool = True) :
    """截取星穹铁道游戏画面

    Args:
        save_path: 截图保存路径
        save_position: 是否保存窗口位置到locate.json
    """
    # 删除之前截取的图片
    delete_file(save_path)

    # 获取主窗口
    window_info = get_starrail_main_window(save_position=save_position)

    if not window_info:
        print("无法获取游戏窗口")
        #删除当前保存窗口坐标的json文件
        json_path=os.path.join(os.path.dirname(__file__), "../../assets/json")
        locate_json_path = os.path.join(json_path,"locate.json")
        delete_file(locate_json_path)
        log.info("无法获取游戏窗口")
        return None

    capture_window_screenshot(window_info['hwnd'], save_path)
def delete_file(file_path):
    """删除指定路径的文件"""
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            print(f"✓ 已删除: {file_path}")
            return True
        else:
            print(f"✗ 文件不存在: {file_path}")
            return False
    except Exception as e:
        print(f"✗ 删除失败: {e}")
        log.error(f"✗ 删除失败: {e}")
        return False

# 使用示例
if __name__ == "__main__":
    # 需要先安装依赖: pip install pywin32 psutil pillow numpy
    time.sleep(4)

    # 截图并保存（会自动保存窗口位置）
    timestamp = int(time.time())
    save_path = f"starrail_screenshot_{timestamp}.png"

