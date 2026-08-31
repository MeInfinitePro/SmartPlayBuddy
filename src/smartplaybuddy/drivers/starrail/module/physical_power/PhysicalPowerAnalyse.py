# -*- coding: utf-8 -*-
"""开拓力识别模块 - 使用RapidOCR识别体力值"""

import re
import json
from pathlib import Path
from typing import Dict, Optional, List, Any

import cv2
import numpy as np
from rapidocr_onnxruntime import RapidOCR

from module.common.OCRCompat import iter_ocr_texts

# ==================== 全局初始化 ====================
_ocr_instance = None


def get_ocr_instance():
    """获取 RapidOCR 单例实例"""
    global _ocr_instance
    if _ocr_instance is None:
        _ocr_instance = RapidOCR(
            use_det=True,
            use_cls=False,
            use_rec=True,
        )
    return _ocr_instance


# ==================== 核心函数 ====================

def img_analyse(img_path: list, debug: bool = False) -> Optional[Dict]:
    """
    识别星穹铁道截图中的开拓力相关数值

    Args:
        img_path: 图片路径列表 [截图路径]
        debug: 是否开启调试模式

    Returns:
        {
            "data": {
                "reserve_power": 2400,  # 后备开拓力 (0-9999)
                "current_power": 257,    # 当前体力值 (0-599)
                "max_power": 300         # 体力上限值
            }
        }
    """
    if not img_path:
        print("[错误] 图片路径为空")
        return None

    # 1. OCR识别图片
    ocr = get_ocr_instance()
    full_text, ocr_results = _ocr_extract_text_with_position(ocr, img_path[0])

    if debug:
        print(f"[调试] OCR识别文本:\n{full_text}\n")
        print("=" * 60)

    if not full_text:
        print("[OCR] 未识别到任何文字")
        return None

    # 2. 提取开拓力相关数值
    power_data = _extract_power_values(full_text, ocr_results, debug)

    if debug:
        print(f"[调试] 提取到的体力数据: {power_data}")

    # 3. 验证数据有效性
    if power_data:
        return {"data": power_data}
    else:
        print("[错误] 未能提取到完整的体力数据")
        return None


# ==================== 体力值提取核心逻辑 ====================

def _extract_power_values(text: str, ocr_results: List, debug: bool = False) -> Dict:
    """
    从OCR文本中提取开拓力相关数值

    提取逻辑：
    1. 查找 "当前/上限" 格式：如 "511/300"
    2. 查找 "后备" 或 "储备" 相关的数字
    3. 验证数值范围：后备(0-9999)、当前(0-599)、上限(200-500)
    """
    result = {
        "reserve_power": 0,
        "current_power": 0,
        "max_power": 0
    }

    # ----- 1. 提取当前体力/上限 (格式: xxx/xxx) -----
    power_pattern = r'(\d{1,3})/(\d{2,4})'
    matches = re.finditer(power_pattern, text)

    for match in matches:
        current = int(match.group(1))
        max_val = int(match.group(2))

        # 验证范围：当前体力 0-599，上限 200-500
        if 0 <= current <= 599 and 200 <= max_val <= 500:
            # 找到最合适的匹配（通常第一个就是体力值）
            if result["current_power"] == 0:
                result["current_power"] = current
                result["max_power"] = max_val
                if debug:
                    print(f"[提取] 当前体力: {current}/{max_val}")
                break

    # 如果没找到标准格式，尝试其他方式
    if result["current_power"] == 0:
        # 尝试查找 "开拓力" 或 "体力" 附近的数字
        result = _extract_power_alternative(text, result, debug)

    # ----- 2. 提取后备开拓力 -----
    reserve_patterns = [
        r'后备[：:]\s*(\d{1,4})',
        r'储备[：:]\s*(\d{1,4})',
        r'后备开拓力[：:]\s*(\d{1,4})',
        r'开拓力储备[：:]\s*(\d{1,4})',
        r'后备\s*(\d{1,4})',
        r'储备\s*(\d{1,4})',
    ]

    for pattern in reserve_patterns:
        match = re.search(pattern, text)
        if match:
            reserve = int(match.group(1))
            # 验证范围：0-9999
            if 0 <= reserve <= 9999:
                result["reserve_power"] = reserve
                if debug:
                    print(f"[提取] 后备开拓力: {reserve}")
                break

    # 如果还没找到后备，尝试从文本中查找其他数字
    if result["reserve_power"] == 0:
        # 查找所有3-4位数字
        all_numbers = re.findall(r'\b(\d{3,4})\b', text)
        for num in all_numbers:
            val = int(num)
            # 后备通常是一个较大的数字（100-9999），且不是体力值
            if 100 <= val <= 9999 and val != result["current_power"] and val != result["max_power"]:
                # 检查这个数字附近是否有"后备"或"储备"关键词
                # 这里简单处理：取第一个符合条件的数字
                if result["reserve_power"] == 0:
                    result["reserve_power"] = val
                    if debug:
                        print(f"[提取] 后备开拓力 (备选): {val}")
                    break

    return result


def _extract_power_alternative(text: str, result: Dict, debug: bool = False) -> Dict:
    """备选方案：通过关键词查找体力值"""

    # 查找 "当前体力" 或 "开拓力" 附近的数字
    keywords = ['开拓力', '体力', '能量', 'power']

    for keyword in keywords:
        pos = text.find(keyword)
        if pos != -1:
            # 提取关键词附近的数字
            context = text[max(0, pos - 20):min(len(text), pos + 50)]
            numbers = re.findall(r'(\d{1,3})', context)

            # 第一个数字通常是当前值，第二个是上限
            if len(numbers) >= 2:
                current = int(numbers[0])
                max_val = int(numbers[1])
                if 0 <= current <= 599 and 200 <= max_val <= 500:
                    result["current_power"] = current
                    result["max_power"] = max_val
                    if debug:
                        print(f"[提取] 通过关键词 '{keyword}' 找到体力: {current}/{max_val}")
                    break

            # 也可能是 "xxx/xxx" 格式的变体
            slash_match = re.search(r'(\d{1,3})/(\d{2,4})', context)
            if slash_match:
                current = int(slash_match.group(1))
                max_val = int(slash_match.group(2))
                if 0 <= current <= 599 and 200 <= max_val <= 500:
                    result["current_power"] = current
                    result["max_power"] = max_val
                    if debug:
                        print(f"[提取] 通过关键词 '{keyword}' 找到体力 (斜杠格式): {current}/{max_val}")
                    break

    return result


# ==================== OCR 工具函数 ====================

def _ocr_extract_text_with_position(ocr: RapidOCR, img_path: str) -> tuple:
    """
    使用 RapidOCR 提取图片中的文字及位置信息

    Returns:
        (完整文本, OCR结果列表)
    """
    try:
        img = cv2.imread(img_path)
        if img is None:
            print(f"[OCR] 无法读取图片: {img_path}")
            return "", []

        # 图片预处理
        img = _preprocess_image(img)
        result, elapse = ocr(img)

        if not result:
            return "", []

        texts = []
        for text, score in iter_ocr_texts(result):
            if text and score > 0.5:
                texts.append(text)

        full_text = " ".join(texts)
        return full_text, result

    except Exception as e:
        print(f"[OCR] 识别失败: {e}")
        return "", []


def _preprocess_image(img: np.ndarray) -> np.ndarray:
    """图片预处理：提升 OCR 识别率"""
    # 转为灰度图
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 自适应直方图均衡化
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)

    # 转为RGB（RapidOCR需要）
    result = cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR)
    return result

if __name__ == '__main__':

    # 手动测试
    assets_path = Path(__file__).resolve().parent.parent.parent.joinpath("assets")
    result = img_analyse(
        img_path=[str(assets_path.joinpath("images", "common", "screenshot.png"))],
        debug=True
    )
    print(result)