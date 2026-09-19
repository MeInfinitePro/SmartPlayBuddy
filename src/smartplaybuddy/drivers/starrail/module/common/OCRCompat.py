# -*- coding: utf-8 -*-
"""
RapidOCR 兼容工具。

不同版本的 RapidOCR 返回格式不一致：
- rapidocr_onnxruntime 1.x：[[box, text, score], ...]，其中 score 在某些版本被
  str() 强转为字符串（如 "0.9876"），直接与 float 比较会抛
  `'>' not supported between instances of 'str' and 'float'`。
- rapidocr 3.x（新包名）：dict 批量格式 {"dt_polys", "rec_texts", "rec_scores"}，
  或单条 dict {"box", "text", "score"}。

本模块提供统一的 score 归一化与文本遍历接口，识别模块无需再关心具体版本。
"""
from typing import Any, Iterator, Optional, Tuple

import numpy as np

_DEFAULT_SCORE = 1.0

# 全角 -> 半角 映射（OCR 输出常见问题）
_FULLWIDTH_MAP = {
    "０": "0", "１": "1", "２": "2", "３": "3", "４": "4",
    "５": "5", "６": "6", "７": "7", "８": "8", "９": "9",
    "／": "/", "－": "-", "：": ":", "，": ",", "；": ";",
    "　": " ",
}


def normalize_ocr_text(text: str) -> str:
    """
    归一化 OCR 输出文本：全角数字/斜杠/标点转半角。

    RapidOCR 对游戏 UI 的识别结果常混有全角斜杠（进度20／120）或数字前后的空格，
    归一化后便于后续正则解析。转换是 1:1 字符映射，不改变文本长度与位置。
    """
    if not text:
        return text
    return text.translate(str.maketrans(_FULLWIDTH_MAP))


def to_float_score(score: Any, default: float = _DEFAULT_SCORE) -> float:
    """
    把任意形式的置信度归一化为 float。

    Args:
        score: str / float / int / numpy 标量 / 单元素列表 / None
        default: 无法解析时的默认值

    Returns:
        float 置信度
    """
    if score is None:
        return default

    if isinstance(score, (float, int)):
        return float(score)

    if isinstance(score, np.generic):
        # numpy 标量：np.float32 / np.float64 / np.int32 等
        try:
            return float(score)
        except Exception:
            return default

    if isinstance(score, np.ndarray):
        try:
            return float(score.item()) if score.size == 1 else default
        except Exception:
            return default

    if isinstance(score, str):
        s = score.strip()
        try:
            return float(s)
        except ValueError:
            return default

    if isinstance(score, (list, tuple)):
        if len(score) == 1:
            return to_float_score(score[0], default)
        return default

    return default


def _get_first(result: dict, *keys: str) -> Any:
    """按 key 顺序取第一个非 None 的值（避免 numpy 真值判断歧义）。"""
    for key in keys:
        if key in result and result[key] is not None:
            return result[key]
    return None


def _iter_dict_result(result: dict) -> Iterator[Tuple[str, float]]:
    """新版 RapidOCR dict 格式。"""
    texts = _get_first(result, "rec_texts", "txts", "texts")
    if texts is not None and len(texts):
        scores = _get_first(result, "rec_scores", "scores")
        if scores is not None and len(scores) == len(texts):
            for text, score in zip(texts, scores):
                yield text, to_float_score(score)
        else:
            for text in texts:
                yield text, _DEFAULT_SCORE
        return

    text = result.get("text")
    if text is not None:
        yield text, to_float_score(result.get("score", _DEFAULT_SCORE))


def iter_ocr_texts(result: Any) -> Iterator[Tuple[str, float]]:
    """
    兼容多种 RapidOCR 返回格式，产出 (text, score) 迭代器。

    支持的格式：
    1. 旧版列表：[[box, text, score], ...]（score 可能是 str）
    2. 单条 dict：{"box", "text", "score"}
    3. 批量 dict：{"dt_polys", "rec_texts", "rec_scores"}
    4. 空 / None / 其他结构：产出空迭代器（不抛异常）

    Args:
        result: RapidOCR 的识别结果

    Yields:
        (text, float_score) 元组
    """
    if result is None:
        return
    if isinstance(result, (list, tuple)) and len(result) == 0:
        return
    if isinstance(result, dict) and len(result) == 0:
        return

    if isinstance(result, dict):
        yield from _iter_dict_result(result)
        return

    if isinstance(result, (list, tuple)):
        for item in result:
            if item is None:
                continue
            if isinstance(item, dict):
                yield from _iter_dict_result(item)
                continue
            if isinstance(item, (list, tuple)):
                # 旧版 [box, text, score] 或 [box, text]
                if len(item) >= 3:
                    yield item[1], to_float_score(item[2])
                elif len(item) == 2:
                    # 兼容 [text, score] 形式
                    yield item[0], to_float_score(item[1])
