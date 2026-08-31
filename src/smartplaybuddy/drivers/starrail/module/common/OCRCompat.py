"""
RapidOCR 返回格式兼容工具。

不同版本的 rapidocr_onnxruntime / rapidocr 返回格式不一致：

- 旧版（如 1.2.x ~ 1.4.x）：list/tuple 格式 `[box, text, score]`，
  且部分版本会把 score 强转成字符串（源码 `str(rec[1])`）。
- 新版（rapidocr 3.x 等）：dict 格式，键名可能是
  `{"box","text","score"}` 或批量格式 `{"dt_polys","rec_texts","rec_scores"}`，
  其中 text/score 可能为列表。

本模块统一归一化为 (text, score) 迭代器，score 保证为 float，
避免 `'>' not supported between instances of 'str' and 'float'` 等类型错误。
"""

from typing import Any, Iterator, Tuple


def to_float_score(value: Any) -> float:
    """将任意形式的 score 归一化为 float；解析失败返回 0.0。"""
    if value is None:
        return 0.0
    if isinstance(value, (list, tuple)):
        return to_float_score(value[0]) if value else 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def iter_ocr_texts(result) -> Iterator[Tuple[str, float]]:
    """从 RapidOCR 返回的 result 中迭代 (text, score)，自动兼容多种格式。"""
    for item in result or []:
        if isinstance(item, dict):
            text = item.get("text") or item.get("rec_texts")
            score = item.get("score") or item.get("rec_scores")

            if isinstance(text, (list, tuple)):
                # 批量格式：rec_texts / rec_scores 为列表
                texts = [t for t in text if isinstance(t, str) and t]
                if isinstance(score, (list, tuple)):
                    scores = list(score)
                else:
                    scores = [score] * len(texts)
                for t, s in zip(texts, scores):
                    yield t, to_float_score(s)
            elif text:
                yield str(text), to_float_score(score)
        else:
            # 旧版 list/tuple 格式：[box, text, score]
            try:
                text = item[1]
                score = item[2]
            except (IndexError, TypeError, ValueError):
                continue
            if text:
                yield str(text), to_float_score(score)
