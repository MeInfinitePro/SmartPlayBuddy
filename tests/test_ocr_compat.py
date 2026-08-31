"""OCR 返回格式兼容测试。

覆盖 rapidocr_onnxruntime 不同版本返回格式：
- 旧版 list/tuple [box, text, score]，其中 score 可能是 str（实际触发
  "'>' not supported between instances of 'str' and 'float'" 的根因）
- 新版 dict 格式 {"box","text","score"} 与批量格式 {"dt_polys","rec_texts","rec_scores"}

不依赖真实文件系统：通过 mock cv2.imread 提供合成图像，全程无需 tmp 目录。
"""
import numpy as np
import pytest

from module.common.OCRCompat import iter_ocr_texts, to_float_score


# ---------------- to_float_score ----------------

def test_to_float_score_variants():
    assert to_float_score("0.9876") == 0.9876
    assert to_float_score(0.9) == 0.9
    assert to_float_score(np.float32(0.8)) == pytest.approx(0.8)
    assert to_float_score(None) == 0.0
    assert to_float_score("abc") == 0.0
    assert to_float_score([0.75]) == 0.75
    assert to_float_score([]) == 0.0
    assert to_float_score((0.6,)) == 0.6


# ---------------- iter_ocr_texts 格式兼容 ----------------

def test_iter_ocr_texts_legacy_float_scores():
    result = [
        [[0, 0, 1, 1], "登录游戏", 0.95],
        [[0, 0, 1, 1], "委托派遣", 0.8],
    ]
    assert list(iter_ocr_texts(result)) == [("登录游戏", 0.95), ("委托派遣", 0.8)]


def test_iter_ocr_texts_legacy_string_scores():
    """实际触发 bug 的格式：rapidocr 把 score 强转为 str。"""
    result = [
        [[0, 0, 1, 1], "开拓力", "0.9876"],
        [[0, 0, 1, 1], "后备", "0.1234"],
    ]
    assert list(iter_ocr_texts(result)) == [("开拓力", 0.9876), ("后备", 0.1234)]


def test_iter_ocr_texts_dict_format():
    result = [
        {"box": [0, 0, 1, 1], "text": "每日实训", "score": 0.99},
        {"box": [0, 0, 1, 1], "text": "体力", "score": "0.66"},
    ]
    assert list(iter_ocr_texts(result)) == [("每日实训", 0.99), ("体力", 0.66)]


def test_iter_ocr_texts_batch_dict_format():
    result = [
        {"dt_polys": [[0, 0, 1, 1], [0, 0, 2, 2]],
         "rec_texts": ["委托派遣或收取1次", "使用1次万能合成台"],
         "rec_scores": [0.95, 0.4]},
    ]
    assert list(iter_ocr_texts(result)) == [("委托派遣或收取1次", 0.95), ("使用1次万能合成台", 0.4)]


def test_iter_ocr_texts_empty_and_garbage():
    assert list(iter_ocr_texts(None)) == []
    assert list(iter_ocr_texts([])) == []
    assert list(iter_ocr_texts([[1, 2]])) == []              # 长度不足
    assert list(iter_ocr_texts([{"no_text_key": 1}])) == []  # dict 缺 text
    assert list(iter_ocr_texts([["box", "", 0.9]])) == []    # 空文本


# ---------------- _ocr_extract_text（真实函数 + 字符串 score） ----------------

def _mock_imread(module, value):
    """mock cv2.imread：返回合成图像或指定值，避免真实文件依赖。"""
    if value is None:
        return lambda path: None
    img = np.zeros((32, 32, 3), dtype=np.uint8)
    return lambda path: img


def test_daily_task_ocr_extract_text_string_scores(monkeypatch):
    """回归测试：DailyTaskAnalyse._ocr_extract_text 处理字符串 score。"""
    from module.daily_task import DailyTaskAnalyse as dta

    monkeypatch.setattr(dta.cv2, "imread", _mock_imread(dta, "img"))

    def fake_ocr(img):
        return (
            [
                [[0, 0, 1, 1], "登录游戏", "0.95"],
                [[0, 0, 1, 1], "低分文本", "0.30"],
            ],
            [0.1, 0.1, 0.1],
        )

    text = dta._ocr_extract_text(fake_ocr, "fake_path.png")
    assert "登录游戏" in text
    assert "低分文本" not in text  # score 0.30 < 0.5 被过滤


def test_daily_task_ocr_extract_text_dict_format(monkeypatch):
    from module.daily_task import DailyTaskAnalyse as dta

    monkeypatch.setattr(dta.cv2, "imread", _mock_imread(dta, "img"))

    def fake_ocr(img):
        return ([{"box": [0, 0, 1, 1], "text": "委托派遣", "score": 0.92}], [0.1])

    assert dta._ocr_extract_text(fake_ocr, "fake_path.png") == "委托派遣"


def test_daily_task_ocr_extract_text_unreadable(monkeypatch):
    from module.daily_task import DailyTaskAnalyse as dta

    monkeypatch.setattr(dta.cv2, "imread", _mock_imread(dta, None))
    # cv2.imread 返回 None（图片不存在）→ 返回空串
    assert dta._ocr_extract_text(lambda img: ([], []), "missing.png") == ""


def test_physical_power_ocr_extract_text_string_scores(monkeypatch):
    """回归测试：PhysicalPowerAnalyse._ocr_extract_text_with_position 处理字符串 score。"""
    from module.physical_power import PhysicalPowerAnalyse as ppa

    monkeypatch.setattr(ppa.cv2, "imread", _mock_imread(ppa, "img"))

    def fake_ocr(img):
        return (
            [
                [[0, 0, 1, 1], "开拓力", "0.98"],
                [[0, 0, 1, 1], "257/300", "0.87"],
                [[0, 0, 1, 1], "杂讯", "0.10"],
            ],
            [0.1, 0.1, 0.1],
        )

    full_text, result = ppa._ocr_extract_text_with_position(fake_ocr, "fake_path.png")
    assert "开拓力" in full_text
    assert "257/300" in full_text
    assert "杂讯" not in full_text
    assert len(result) == 3  # 原始 result 原样保留（供位置信息使用）
