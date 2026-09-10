# -*- coding: utf-8 -*-
"""每日实训任务分析模块 - 识别未完成任务（三月七小助手方案）

核心逻辑：
1. 已完成且已领取：进度条满（如 1/1）且包含"领取"关键字
2. 已完成但未领取：进度条满（如 1/1）且包含"领取"关键字
3. 未完成：进度条未满（如 0/120 或 6/20）
4. 只返回未完成的任务
"""

import json
import re
from pathlib import Path
from typing import List, Dict, Optional, Any

import cv2
import numpy as np
from rapidocr_onnxruntime import RapidOCR

from module.common.OCRCompat import iter_ocr_texts, normalize_ocr_text

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

def daily_task_analyse(img_path: list, debug: bool = False) -> List[Dict]:
    """
    识别每日实训任务中【未完成】的任务（支持多张图片合并去重）

    Args:
        img_path: 图片路径列表 [任务列表截图1, 任务列表截图2]
        debug: 是否开启调试模式

    Returns:
        未完成任务列表，格式: [{"id": 1, "name": "任务名称"}, ...]
    """
    if not img_path or len(img_path) < 2:
        print("[错误] 图片路径列表不完整，至少需要2张图片")
        return []

    # 1. 分别识别两张图片
    ocr = get_ocr_instance()
    all_task_items = []

    for i, path in enumerate(img_path):
        full_text = _ocr_extract_text(ocr, path)
        if debug:
            print(f"[调试] 图片{i + 1} OCR识别文本:\n{full_text[:200]}...\n")
            print("=" * 60)

        # 提取该图片中的所有任务项
        task_items = _extract_task_items(full_text)
        all_task_items.extend(task_items)

        if debug:
            print(f"[调试] 图片{i + 1} 提取到 {len(task_items)} 个任务项")
            for item in task_items:
                status = "✅ 已完成" if item["is_completed"] else "❌ 未完成"
                print(f"  {item['name']} - {item['progress_text']} ({status})")
            print("=" * 60)

    if not all_task_items:
        print("[OCR] 未识别到任何任务")
        return []

    # 2. 合并去重：按任务名称去重，保留进度信息
    merged_tasks = _merge_task_items(all_task_items)

    if debug:
        print(f"[调试] 合并去重后共 {len(merged_tasks)} 个任务项:")
        for item in merged_tasks:
            status = "✅ 已完成" if item["is_completed"] else "❌ 未完成"
            print(f"  {item['name']} - {item['progress_text']} ({status})")
        print("=" * 60)

    # 3. 筛选【未完成】的任务
    incomplete_tasks = []

    for item in merged_tasks:
        if not item["is_completed"]:  # 未完成
            # 尝试匹配本地任务ID
            task_id = _find_task_id(item["name"])

            # 如果找不到匹配的ID，使用临时ID
            if task_id is None:
                task_id = f"temp_{len(incomplete_tasks) + 1}"
                if debug:
                    print(f"[警告] 任务 '{item['name']}' 在本地列表中无匹配ID，分配临时ID: {task_id}")

            incomplete_tasks.append({
                "id": task_id,
                "name": item["name"],
            })

            if debug:
                print(f"[未完成] ❌ {item['name']} - 进度 {item['progress_text']}")
        else:
            if debug:
                print(f"[已完成] ✅ {item['name']} - 进度 {item['progress_text']}")

    if incomplete_tasks:
        print(f"[结果] 找到 {len(incomplete_tasks)} 个未完成任务")
        return incomplete_tasks
    else:
        print("[结果] 所有任务已完成！")
        return []


# ==================== 任务合并去重逻辑 ====================

def _merge_task_items(task_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    合并多张图片的任务项，按任务名称去重
    """
    task_map = {}

    for item in task_items:
        name = item.get("name", "")
        if not name:
            continue

        progress_text = item.get("progress_text", "")
        is_completed = item.get("is_completed", False)
        current = item.get("current", 0)
        total = item.get("total", 0)
        has_claim_keyword = item.get("has_claim_keyword", False)

        if name not in task_map:
            task_map[name] = {
                "name": name,
                "progress_text": progress_text,
                "is_completed": is_completed,
                "current": current,
                "total": total,
                "has_claim_keyword": has_claim_keyword,
                "pos": item.get("pos", 0),
                "source_count": 1
            }
        else:
            existing = task_map[name]
            existing["source_count"] += 1

            # 优先选择进度更完整的信息
            if progress_text and not existing["progress_text"]:
                existing["progress_text"] = progress_text
                existing["is_completed"] = is_completed
                existing["current"] = current
                existing["total"] = total
                existing["has_claim_keyword"] = has_claim_keyword
            elif progress_text and existing["progress_text"]:
                # 如果进度信息都完整，选择更准确的
                if current > existing.get("current", 0):
                    existing["progress_text"] = progress_text
                    existing["is_completed"] = is_completed
                    existing["current"] = current
                    existing["total"] = total
                    existing["has_claim_keyword"] = has_claim_keyword

    merged_list = list(task_map.values())
    merged_list.sort(key=lambda x: x.get("pos", 0))

    return merged_list


# ==================== 任务提取核心逻辑 ====================

def _extract_task_items(ocr_text: str) -> List[Dict[str, Any]]:
    """
    从OCR文本中提取所有任务项（任务名称 + 进度 + 完成状态）

    判断逻辑：
    1. 进度条满（current >= total）且包含"领取"关键字 → 已完成
    2. 进度条满（current >= total）但不包含"领取"关键字 → 已完成（等待领取）
    3. 进度条未满（current < total） → 未完成
    """
    if not ocr_text:
        return []

    # 归一化（全角 -> 半角），容忍 OCR 的空格/全角斜杠
    ocr_text = normalize_ocr_text(ocr_text)

    # ----- 1. 提取所有进度信息 -----
    progress_matches = []
    for match in re.finditer(r'进度\s*(\d{1,3})\s*/\s*(\d{1,3})', ocr_text):
        current = int(match.group(1))
        total = int(match.group(2))

        # 检查进度附近是否有"领取"关键字
        # 取进度前后50个字符的上下文
        start_pos = max(0, match.start() - 50)
        end_pos = min(len(ocr_text), match.end() + 50)
        context = ocr_text[start_pos:end_pos]

        has_claim = "领取" in context or "领" in context

        # 判断是否完成：进度条满即为完成
        is_completed = current >= total

        progress_matches.append({
            "current": current,
            "total": total,
            "pos": match.start(),
            "end": match.end(),
            "text": match.group(0),
            "is_completed": is_completed,
            "has_claim_keyword": has_claim
        })

    if not progress_matches:
        return []

    # ----- 2. 提取所有任务名称 -----
    task_candidates = _extract_task_candidates(ocr_text)

    # ----- 3. 按位置排序并匹配 -----
    task_candidates.sort(key=lambda x: x["pos"])
    progress_matches.sort(key=lambda x: x["pos"])

    # ----- 4. 一一对应匹配 -----
    task_items = []
    for i, task in enumerate(task_candidates):
        if i < len(progress_matches):
            progress = progress_matches[i]
            task_items.append({
                "name": task["name"],
                "pos": task["pos"],
                "progress_text": progress["text"],
                "current": progress["current"],
                "total": progress["total"],
                "is_completed": progress["is_completed"],
                "has_claim_keyword": progress["has_claim_keyword"],
                "raw_text": task["raw_text"]
            })

    return task_items


def _extract_task_candidates(ocr_text: str) -> List[Dict[str, Any]]:
    """从OCR文本中提取任务名称候选"""
    task_keywords = [
        "登录游戏", "拍照", "委托", "消耗", "开拓", "消灭", "击败",
        "模拟宇宙", "差分宇宙", "侵蚀隧道", "遗器", "光锥",
        "秘技", "弱点击破", "支援角色", "合成台", "派遣",
        "收取", "完成", "累计", "使用"
    ]

    candidates = []
    for keyword in task_keywords:
        pos = ocr_text.find(keyword)
        if pos != -1:
            task_name = _extract_full_task_name(ocr_text, pos, keyword)
            if task_name and len(task_name) > 1:
                candidates.append({
                    "name": task_name,
                    "pos": pos,
                    "raw_text": task_name
                })

    # 去重（保留位置最前的）
    seen = set()
    unique_candidates = []
    for item in candidates:
        if item["name"] not in seen:
            seen.add(item["name"])
            unique_candidates.append(item)

    return unique_candidates


def _extract_full_task_name(ocr_text: str, pos: int, keyword: str) -> str:
    """提取包含关键词的完整任务名称"""
    separators = ['。', '，', '、', '；', '：', ' ', '\n', '\t', '进度']

    start = pos
    end = pos + len(keyword)

    # 向前扩展
    while start > 0:
        char = ocr_text[start - 1]
        if char.isdigit() or '\u4e00' <= char <= '\u9fff':
            start -= 1
        else:
            break

    # 向后扩展
    while end < len(ocr_text):
        char = ocr_text[end]
        if '\u4e00' <= char <= '\u9fff' or char.isdigit() or char == '：' or char == ':':
            end += 1
        else:
            if char == '进' and end + 1 < len(ocr_text) and ocr_text[end + 1] == '度':
                break
            if char in separators:
                break
            end += 1

    task_name = ocr_text[start:end].strip()

    if '进度' in task_name:
        task_name = task_name.split('进度')[0].strip()

    if len(task_name) < 2 or len(task_name) > 30:
        return keyword

    return task_name


# ==================== 任务ID匹配 ====================

def _find_task_id(ocr_task_name: str) -> Optional[int]:
    """通过OCR识别的任务名称，在 daily_task.json 中查找对应的ID"""
    json_path = Path(__file__).resolve().parent.parent.parent.joinpath("assets", "json")
    task_list = _load_json_file(json_path.joinpath("daily_task.json"))

    if not task_list:
        print("[警告] 无法加载 daily_task.json 文件，无法匹配任务ID。")
        return None

    task_list = _parse_task_list(task_list)
    if not task_list:
        print("[警告] daily_task.json 文件格式无效或为空。")
        return None

    # 清理OCR任务名称
    ocr_task_name = ocr_task_name.strip()
    if not ocr_task_name:
        return None

    # 策略1：精确匹配
    for task in task_list:
        json_task_name = task.get("name", "").strip()
        if ocr_task_name == json_task_name:
            print(f"[匹配] 精确匹配成功: '{ocr_task_name}' -> ID: {task.get('id')}")
            return task.get("id")

    # 策略2：关键词匹配
    print(f"[匹配] 精确匹配失败，尝试关键词匹配: '{ocr_task_name}'")
    ocr_keywords = _extract_keywords(ocr_task_name)

    for task in task_list:
        json_task_name = task.get("name", "").strip()
        json_keywords = _extract_keywords(json_task_name)

        if set(ocr_keywords) & set(json_keywords):
            print(f"[匹配] 关键词匹配成功: '{ocr_task_name}' 匹配到 '{json_task_name}' -> ID: {task.get('id')}")
            return task.get("id")

    print(f"[匹配] 警告: 未能为 '{ocr_task_name}' 匹配到任何ID。")
    return None


def _extract_keywords(text: str) -> List[str]:
    """从任务名称中提取关键词"""
    stop_words = ["完成", "一次", "累计", "进行", "次", "个", "点", "的", "了", "派遣", "收取"]
    known_keywords = ["登录游戏", "模拟宇宙", "差分宇宙", "侵蚀隧道", "拍照",
                      "委托", "开拓力", "开拓", "敌人", "弱点击破", "遗器", "光锥",
                      "秘技", "支援角色", "合成台", "消耗", "消灭", "击败"]

    cleaned = text
    for word in stop_words:
        cleaned = cleaned.replace(word, "")

    keywords = [cleaned.strip()] if cleaned.strip() else []

    for item in known_keywords:
        if item in text and item not in keywords:
            keywords.append(item)

    if not keywords:
        keywords = [text]

    return keywords


# ==================== OCR 工具函数 ====================

# 大图降采样宽度上限：1924x1140 全图 OCR 单张可达 10-20s；
# 游戏 UI 文字较大，缩到 1280 宽后速度提升数倍且识别率基本不变
MAX_OCR_WIDTH = 1280


def _ocr_extract_text(ocr: RapidOCR, img_path: str) -> str:
    """使用 RapidOCR 提取图片中的文字（兼容多种 RapidOCR 版本返回格式）"""
    try:
        img = cv2.imread(img_path)
        if img is None:
            print(f"[OCR] 无法读取图片: {img_path}")
            return ""

        h, w = img.shape[:2]
        if w > MAX_OCR_WIDTH:
            scale = MAX_OCR_WIDTH / w
            img = cv2.resize(img, (MAX_OCR_WIDTH, int(h * scale)),
                             interpolation=cv2.INTER_AREA)

        img = _preprocess_image(img)
        result, elapse = ocr(img)

        if not result:
            return ""

        texts = []
        for text, score in iter_ocr_texts(result):
            if text and score > 0.5:
                texts.append(text)

        return normalize_ocr_text(" ".join(texts))

    except Exception as e:
        print(f"[OCR] 识别失败: {e}")
        return ""


def _preprocess_image(img: np.ndarray) -> np.ndarray:
    """图片预处理：提升 OCR 识别率"""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    result = cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR)
    return result


# ==================== JSON 加载工具 ====================

def _load_json_file(file_path: Path) -> Optional[Any]:
    """加载 JSON 文件"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"[错误] 加载JSON文件失败: {e}")
        return None


def _parse_task_list(data) -> List[Dict]:
    """解析任务列表，兼容多种数据格式"""
    if isinstance(data, list):
        return data
    elif isinstance(data, dict):
        for key in ["tasks", "task_list", "data", "result"]:
            if key in data and isinstance(data[key], list):
                return data[key]
    return []


# ==================== 使用示例 ====================

if __name__ == '__main__':
    test_images = [
        "../../assets/images/common/shot1.png",
        "../../assets/images/common/shot2.png",
    ]

    # 启用调试模式
    result = daily_task_analyse(test_images, debug=True)
    print(result)
    # print(f"\n最终结果: {result}")