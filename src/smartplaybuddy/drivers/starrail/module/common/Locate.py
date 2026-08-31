import time

import cv2
import os
import numpy as np
import json
import pyautogui
from utils.log.Log import Log
from module.common.Capture import screen_capture as sc
from pathlib import Path
log=Log()

import cv2
import numpy as np


def locate_image_precise(screenshot_path, target_path, threshold=0.65):
    """
    高精度图像定位 - 使用特征点匹配（推荐）
    精度最高，对旋转、缩放、光照变化都有很好的鲁棒性
    """
    # 读取图片
    screenshot = cv2.imread(screenshot_path)
    target = cv2.imread(target_path)

    if screenshot is None or target is None:
        print("图片读取失败")
        return None

    # 转换为灰度图
    screenshot_gray = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)
    target_gray = cv2.cvtColor(target, cv2.COLOR_BGR2GRAY)

    # 使用SIFT特征检测器（精度最高）
    # 如果没有SIFT，可以使用ORB（稍慢但同样精确）
    try:
        # 优先使用SIFT（精度最高）
        sift = cv2.SIFT_create()
        kp1, des1 = sift.detectAndCompute(target_gray, None)
        kp2, des2 = sift.detectAndCompute(screenshot_gray, None)
    except:
        # 备用ORB
        orb = cv2.ORB_create(nfeatures=2000)
        kp1, des1 = orb.detectAndCompute(target_gray, None)
        kp2, des2 = orb.detectAndCompute(screenshot_gray, None)

    if des1 is None or des2 is None:
        print("特征点检测失败")
        return None

    # 特征匹配（使用FLANN匹配器）
    FLANN_INDEX_KDTREE = 1
    index_params = dict(algorithm=FLANN_INDEX_KDTREE, trees=5)
    search_params = dict(checks=50)
    flann = cv2.FlannBasedMatcher(index_params, search_params)

    try:
        matches = flann.knnMatch(des1, des2, k=2)
    except:
        # 如果FLANN失败，使用BFMatcher
        bf = cv2.BFMatcher()
        matches = bf.knnMatch(des1, des2, k=2)

    # 应用比率测试筛选优质匹配
    good_matches = []
    for m, n in matches:
        if m.distance < 0.75 * n.distance:
            good_matches.append(m)

    # 检查匹配数量是否足够
    min_match_count = 10
    if len(good_matches) < min_match_count:
        print(f"匹配点不足: {len(good_matches)}/{min_match_count}")
        return None

    # 提取匹配点的坐标
    src_pts = np.float32([kp1[m.queryIdx].pt for m in good_matches]).reshape(-1, 1, 2)
    dst_pts = np.float32([kp2[m.trainIdx].pt for m in good_matches]).reshape(-1, 1, 2)

    # 计算透视变换矩阵
    M, mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 5.0)

    if M is None:
        print("计算变换矩阵失败")
        return None

    # 获取目标图的四个角点
    h, w = target.shape[:2]
    pts = np.float32([[0, 0], [0, h - 1], [w - 1, h - 1], [w - 1, 0]]).reshape(-1, 1, 2)

    # 将目标图的角点映射到截图中
    dst = cv2.perspectiveTransform(pts, M)

    # 计算中心点
    center_x = int(np.mean(dst[:, 0, 0]))
    center_y = int(np.mean(dst[:, 0, 1]))

    # 计算匹配质量分数
    match_ratio = len(good_matches) / len(matches) if matches else 0
    if match_ratio >= threshold:
        return (center_x, center_y)
    else:
        print(f"匹配质量不足: {match_ratio:.3f}")
        return None


def locate_image_fast(screenshot_path, target_path, threshold=0.75):
    """
    快速定位 - 多尺度+金字塔模板匹配
    速度比特征点快5-10倍，精度也不错
    """
    screenshot = cv2.imread(screenshot_path)
    target = cv2.imread(target_path)

    if screenshot is None or target is None:
        return None

    # 图像金字塔（多分辨率）
    best_match = None
    best_val = -1
    best_scale = 1.0
    best_loc = None

    # 多尺度搜索
    for scale in [0.8, 0.9, 1.0, 1.1, 1.2]:
        # 缩放目标
        new_w = int(target.shape[1] * scale)
        new_h = int(target.shape[0] * scale)
        if new_w < 10 or new_h < 10:
            continue

        scaled_target = cv2.resize(target, (new_w, new_h))

        # 模板匹配
        result = cv2.matchTemplate(screenshot, scaled_target, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)

        if max_val > best_val:
            best_val = max_val
            best_scale = scale
            best_loc = max_loc

    if best_val >= threshold:
        # 亚像素精确定位
        x, y = best_loc
        w = int(target.shape[1] * best_scale)
        h = int(target.shape[0] * best_scale)
        center_x = x + w // 2
        center_y = y + h // 2

        return (center_x, center_y)

    return None


def locate_image(screenshot_path, target_path, threshold=0.7):
    """
    智能选择最佳方法
    """
    # 先尝试特征点匹配（精度最高）
    result = locate_image_precise(screenshot_path, target_path, threshold)
    if result:
        return result

    # 特征点匹配失败，使用多尺度模板匹配
    print("特征点匹配失败，尝试多尺度模板匹配...")
    result = locate_image_fast(screenshot_path, target_path, threshold)
    if result:
        return result

    print("所有方法都未能匹配成功")
    return None

class GetPosition:
    def __init__(self):
        self.assets_path = Path(__file__).resolve().parent.parent.parent.joinpath('assets')
        #默认屏幕截图保存路径
        self.screenshot_path=self.assets_path.joinpath('images',"common",'screenshot.png')
        #指定游戏界面实际左上将的指标信息存储位置
        self.locate_json=self.assets_path.joinpath('json','locate.json')
    def get_actual_position(self,ps):
        #获取匹配图片在游戏窗口中的位置
        if ps!= None:
            if os.path.exists(self.locate_json):
                with open(self.locate_json, 'r', encoding='utf-8') as f:
                    existing_data = json.load(f)
                    position = existing_data['last_window_position']['rect']
                    x, y = position[0], position[1]
                    x, y = ps[0] + x, ps[1] + y
                    if x>0 and y>0:
                        return (x, y)
                    else:
                        return None
        else:
            print("图片匹配失败")
            return None
    def get_target_pos(self,save_path:str=None,target_path:str=""):
        if save_path is not None:
            self.screenshot_path=save_path
        try:
            sc(self.screenshot_path)
            ps = locate_image(self.screenshot_path, target_path)
            return self.get_actual_position(ps)
        except Exception as e:
            print(f"出现错误:{e}")
            log.error(f"出现错误:{e}")
            return None
    def printf(self):
        print(self.assets_path)
# 使用示例
if __name__ == "__main__":
   pass
