"""每日实训任务分析逻辑测试（纯 Python 逻辑，不依赖真实 OCR 引擎）。"""
from pathlib import Path

import pytest

from module.daily_task.DailyTaskAnalyse import (
    daily_task_analyse,
    _extract_task_items,
    _merge_task_items,
    _find_task_id,
    _extract_task_candidates,
    _parse_task_list,
)


# ---------------- 任务项提取 ----------------

def test_extract_task_items_mixed_completed_and_incomplete():
    text = "登录游戏 进度1/1 领取 委托派遣或收取1次 进度0/1 累计消灭20个敌人 进度5/20"
    items = _extract_task_items(text)
    by_name = {it["name"]: it for it in items}

    assert "登录游戏" in by_name
    assert by_name["登录游戏"]["is_completed"] is True
    assert by_name["登录游戏"]["has_claim_keyword"] is True

    assert "委托派遣或收取1次" in by_name
    assert by_name["委托派遣或收取1次"]["is_completed"] is False

    assert "累计消灭20个敌人" in by_name
    assert by_name["累计消灭20个敌人"]["current"] == 5
    assert by_name["累计消灭20个敌人"]["total"] == 20


def test_extract_task_items_empty_text():
    assert _extract_task_items("") == []
    assert _extract_task_items(None) == []


def test_extract_task_items_no_progress():
    # 只有任务名没有进度 → 无法构成任务项
    assert _extract_task_items("登录游戏 委托派遣") == []


# ---------------- 任务合并去重 ----------------

def test_merge_task_items_dedup_keeps_progress():
    items = [
        {"name": "登录游戏", "progress_text": "进度1/1", "is_completed": True,
         "current": 1, "total": 1, "has_claim_keyword": True, "pos": 0},
        {"name": "登录游戏", "progress_text": "进度1/1", "is_completed": True,
         "current": 1, "total": 1, "has_claim_keyword": True, "pos": 0},
        {"name": "委托派遣或收取1次", "progress_text": "进度0/1", "is_completed": False,
         "current": 0, "total": 1, "has_claim_keyword": False, "pos": 5},
    ]
    merged = _merge_task_items(items)
    assert len(merged) == 2
    assert merged[0]["name"] == "登录游戏"
    assert merged[0]["source_count"] == 2
    assert merged[1]["name"] == "委托派遣或收取1次"


def test_merge_task_items_empty():
    assert _merge_task_items([]) == []


# ---------------- 任务名候选提取 ----------------

def test_extract_task_candidates():
    text = "委托派遣或收取1次 进度0/1 使用1次万能合成台 进度0/1"
    cands = _extract_task_candidates(text)
    names = {c["name"] for c in cands}
    assert "委托派遣或收取1次" in names
    assert "使用1次万能合成台" in names


# ---------------- 任务 ID 匹配 ----------------

def test_find_task_id_exact_match():
    assert _find_task_id("登录游戏") == 1
    assert _find_task_id("使用1次万能合成台") == 9
    assert _find_task_id("完成一次拍照") == 10


def test_find_task_id_keyword_match():
    assert _find_task_id("拍照") == 10
    assert _find_task_id("派遣委托或收取1次") == 2


def test_find_task_id_no_match():
    assert _find_task_id("完全不存在的任务") is None
    assert _find_task_id("") is None


# ---------------- JSON 解析 ----------------

def test_parse_task_list_formats():
    assert _parse_task_list([{"id": 1}]) == [{"id": 1}]
    assert _parse_task_list({"tasks": [{"id": 2}]}) == [{"id": 2}]
    assert _parse_task_list({"data": [{"id": 3}]}) == [{"id": 3}]
    assert _parse_task_list({}) == []
    assert _parse_task_list(None) == []


# ---------------- daily_task_analyse 编排（mock OCR） ----------------

def _make_fake_ocr(texts):
    def fake_ocr(ocr, img_path):
        idx = int(Path(str(img_path)).stem[-1]) - 1
        return texts[idx] if 0 <= idx < len(texts) else ""
    return fake_ocr


def test_daily_task_analyse_returns_incomplete(monkeypatch):
    from module.daily_task import DailyTaskAnalyse as dta

    monkeypatch.setattr(dta, "get_ocr_instance", lambda: None)
    monkeypatch.setattr(dta, "_ocr_extract_text", _make_fake_ocr([
        "登录游戏 进度1/1 领取 委托派遣或收取1次 进度0/1",
        "委托派遣或收取1次 进度0/1 使用1次万能合成台 进度0/1",
    ]))

    result = dta.daily_task_analyse(["shot1.png", "shot2.png"])
    ids = {t["id"] for t in result}
    assert 2 in ids      # 委托派遣（未完成）
    assert 9 in ids      # 合成台（未完成）
    assert 1 not in ids  # 登录游戏已完成
    assert 10 not in ids  # 拍照未出现在文本中


def test_daily_task_analyse_all_completed(monkeypatch):
    from module.daily_task import DailyTaskAnalyse as dta

    monkeypatch.setattr(dta, "get_ocr_instance", lambda: None)
    monkeypatch.setattr(dta, "_ocr_extract_text",
                        _make_fake_ocr(["登录游戏 进度1/1 领取", "登录游戏 进度1/1 领取"]))

    result = dta.daily_task_analyse(["shot1.png", "shot2.png"])
    assert result == []


def test_daily_task_analyse_requires_two_images(monkeypatch):
    from module.daily_task import DailyTaskAnalyse as dta

    monkeypatch.setattr(dta, "get_ocr_instance", lambda: None)
    monkeypatch.setattr(dta, "_ocr_extract_text", lambda ocr, path: "")
    assert dta.daily_task_analyse(["only_one.png"]) == []
    assert dta.daily_task_analyse(None) == []
