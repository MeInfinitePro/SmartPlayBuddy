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


# PrintWindow 标志：要求 Windows 8.1+，可抓取 DWM/GPU 渲染内容，
# 窗口被其他窗口遮挡时也能截到游戏画面
PW_RENDERFULLCONTENT = 0x00000002


_WGC_IMPORT_ERR_SHOWN = False


def capture_window_content_wgc(hwnd: int, save_path: Optional[str] = None, timeout: float = 5.0):
    """通过 Windows.Graphics.Capture API 抓取窗口内容（Win10 1903+）。

    这是唯一能可靠抓取 DirectX/Unity 硬件渲染窗口的方案：
    PrintWindow 对星穹铁道这类窗口会被系统直接拒绝（返回 0），
    而 WGC 不受窗口遮挡/前台状态影响。依赖可选包 windows-capture，
    未安装时返回 None，由调用方走后续回退链。
    """
    global _WGC_IMPORT_ERR_SHOWN
    try:
        import threading
        from windows_capture import WindowsCapture
    except ImportError:
        if not _WGC_IMPORT_ERR_SHOWN:
            print("未安装 windows-capture（pip install windows-capture），WGC 抓取不可用")
            _WGC_IMPORT_ERR_SHOWN = True
        return None

    try:
        left, top, right, bottom = get_window_rect_accurate(hwnd)
        if right - left <= 0 or bottom - top <= 0 or left < -20000 or top < -20000:
            print("窗口不可用（可能已最小化）")
            return None

        latest = {}
        evt = threading.Event()

        def frame_handler(frame, control):
            if "np" not in latest:
                latest["np"] = frame.frame_buffer
                evt.set()
            control.stop()

        cap = WindowsCapture(cursor_capture=False, draw_border=False, window_hwnd=hwnd)
        cap.frame_handler = frame_handler
        cap.closed_handler = lambda: None

        control = cap.start_free_threaded()
        try:
            if not evt.wait(timeout):
                print("WGC 抓取超时")
                return None
        finally:
            try:
                control.stop()
            except Exception:
                pass

        arr = latest["np"]  # BGRA
        if arr.size == 0 or arr.ndim != 3:
            return None
        from PIL import Image
        img = Image.fromarray(arr[..., :3][..., ::-1])  # BGRA → RGB

        # 纯色帧检测：WGC 会话刚建立时可能收到初始化黑帧
        gray = np.asarray(img.convert("L"))
        if gray.size == 0 or float(gray.std()) < 1.0:
            print("WGC 截到纯色帧，判定为抓取失败")
            return None

        if save_path:
            img.save(save_path)
        return img
    except Exception as e:
        print(f"WGC 窗口内容截图时出错: {e}")
        return None


def capture_window_content(hwnd: int, save_path: Optional[str] = None):
    """通过 PrintWindow 抓取窗口自身内容（不依赖窗口是否被遮挡/在前台）。

    注意：星穹铁道这类 DirectX 硬件渲染窗口会直接拒绝 PrintWindow
    （返回 0），此路径主要对普通窗口生效，作为 WGC 之后的回退。
    返回 PIL.Image，失败返回 None（调用方应回退到屏幕区域截图）。
    """
    try:
        import win32ui
        import win32gui
        from PIL import Image

        left, top, right, bottom = get_window_rect_accurate(hwnd)
        # 最小化时窗口坐标为 -32000 附近，直接判定无效
        if right - left <= 0 or bottom - top <= 0 or left < -20000 or top < -20000:
            print("窗口不可用（可能已最小化）")
            return None
        width, height = right - left, bottom - top

        hwnd_dc = win32gui.GetWindowDC(hwnd)
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()
        bmp = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(mfc_dc, width, height)
        save_dc.SelectObject(bmp)

        try:
            result = ctypes.windll.user32.PrintWindow(
                hwnd, save_dc.GetSafeHdc(), PW_RENDERFULLCONTENT)
            if result != 1:
                print("PrintWindow 调用失败")
                return None
            bmpinfo = bmp.GetInfo()
            bmpstr = bmp.GetBitmapBits(True)
            img = Image.frombuffer(
                "RGB",
                (bmpinfo["bmWidth"], bmpinfo["bmHeight"]),
                bmpstr, "raw", "BGRX", 0, 1)
        finally:
            try:
                win32gui.DeleteObject(bmp.GetHandle())
                save_dc.DeleteDC()
                mfc_dc.DeleteDC()
                win32gui.ReleaseDC(hwnd, hwnd_dc)
            except Exception:
                pass

        # 全黑/纯色检测：硬件渲染异常时 PrintWindow 可能返回整帧纯色，
        # 此时视为失败，交由调用方回退到 ImageGrab
        arr = np.asarray(img.convert("L"))
        if arr.size == 0 or float(arr.std()) < 1.0:
            print("PrintWindow 截到纯色帧，判定为抓取失败")
            return None

        if save_path:
            img.save(save_path)
        return img

    except Exception as e:
        print(f"窗口内容截图时出错: {e}")
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
            if found_pid == target_pid and win32gui.IsWindowVisible(hwnd) and not win32gui.IsIconic(hwnd):
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
        log.info(f"  标题: {main_window_info['title']}")
        log.info(f"  尺寸: {main_window_info['width']}x{main_window_info['height']}")

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


# 主窗口缓存：避免每次定位都 psutil 全进程扫描 + EnumWindows（单次可省数百毫秒）
_WINDOW_CACHE: Dict = {"hwnd": None, "pid": None, "rect": None}


def _get_cached_main_hwnd() -> Optional[int]:
    """带缓存的星铁道主窗口句柄获取。

    缓存有效条件：句柄仍是可见窗口，且所属进程仍是 StarRail.exe。
    任一条件不满足则做一次全量查找并刷新缓存。
    """
    hwnd = _WINDOW_CACHE.get("hwnd")
    if hwnd is not None:
        try:
            # 可见且未最小化（最小化窗口 IsWindowVisible 仍为 True，但坐标移出屏幕）
            if (win32gui.IsWindow(hwnd) and win32gui.IsWindowVisible(hwnd)
                    and not win32gui.IsIconic(hwnd)):
                pid = win32process.GetWindowThreadProcessId(hwnd)[1]
                if psutil.Process(pid).name() == "StarRail.exe":
                    return hwnd
        except Exception:
            pass
        _WINDOW_CACHE.update({"hwnd": None, "pid": None, "rect": None})

    info = get_starrail_main_window(save_position=False)
    if info is None:
        return None
    _WINDOW_CACHE.update({
        "hwnd": info["hwnd"],
        "pid": win32process.GetWindowThreadProcessId(info["hwnd"])[1],
        "rect": info["rect"],
    })
    return info["hwnd"]


def screen_capture(save_path: Optional[str] = os.path.join(os.path.dirname(__file__),"data","screenshot.png"), save_position: bool = True) :
    """截取星穹铁道游戏画面

    Args:
        save_path: 截图保存路径
        save_position: 保留参数（历史兼容），不再写 locate.json

    截图策略：优先 WGC 抓窗口内容（游戏被其他窗口遮挡时依然有效），
    失败回退 PrintWindow，再回退 ImageGrab 按屏幕 bbox 截图。
    窗口位置坐标已改为实时获取（见 Locate.get_actual_position），
    不再依赖 locate.json 缓存。
    """
    # 删除之前截取的图片
    delete_file(save_path)

    # 获取主窗口（带缓存）
    hwnd = _get_cached_main_hwnd()

    if not hwnd:
        print("无法获取游戏窗口")
        log.info("无法获取游戏窗口")
        return None

    # 优先 WGC（抗遮挡、支持 DirectX 窗口）→ PrintWindow → 屏幕区域截图
    img = capture_window_content_wgc(hwnd, save_path)
    if img is None:
        img = capture_window_content(hwnd, save_path)
    if img is None:
        print("回退到屏幕区域截图（ImageGrab）")
        capture_window_screenshot(hwnd, save_path)
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

