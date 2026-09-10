import time
from typing import Optional, Tuple
from pathlib import Path
import pyautogui

from module.common.Locate import GetPosition
from utils.log.Log import Log
log = Log()


pos = GetPosition()
imag_path = Path(__file__).resolve().parent.parent.parent.joinpath("assets","images")
common_img_path = imag_path.joinpath("common")

def wait_until(image_key: str,
               timeout: float = 10.0,
               confidence: float = 0.8,
               interval: float = 0.3) -> Optional[Tuple[int, int]]:
    """
    动态等待，直到目标图像出现在屏幕上
    返回目标中心坐标，超时返回 None
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            pos_target = pos.get_target_pos(target_path=image_key)
            if pos_target is not None:
                log.info(f"找到目标的位置{pos_target}")
                return pos_target
        except Exception:
            pass
        time.sleep(interval)
    print(f"⏰ 等待超时: {image_key}")
    return None

def wait_and_click(image_key: str,
                   timeout: float = 10.0,
                   confidence: float = 0.8,
                   clicks: int = 1,
                   interval: float = 0.3) -> bool:
    """
    等待元素出现并点击
    返回是否成功点击
    """
    pos_target = wait_until(image_key, timeout, confidence, interval)
    if pos_target is not None:
        pyautogui.click(pos_target, clicks=clicks)
        return True
    return False

def wait_and_press(key: str, timeout: float = 10.0, condition_image: str = None):
    """
    按下按键，并可选地等待某个图像出现来确认界面已切换
    """
    pyautogui.press(key)
    if condition_image:
        return wait_until(condition_image, timeout) is not None
    return True
def interface_switch(cx,cy):
    """

    :param cx: 要调整的x轴值
    :param cy: 要调整的y轴值
    :return:
    """
    target = wait_until(common_img_path.joinpath("interstellar_guide.png"), timeout=5.0)
    if target is None:
        print("当前不在星际和平指南界面")
        log.info(f"{common_img_path.joinpath('interstellar_guide.png')}")
        return None

    # 直接复用 wait_until 返回的坐标，避免再次全图定位（每次定位 3-5s）
    x, y = target
    pyautogui.click(x + cx, y + cy)
    log.info(f"x-cx,y-cy:{x},{y}")
    return True
