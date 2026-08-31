"""开拓力识别逻辑测试（纯 Python 逻辑，不依赖真实 OCR 引擎）。"""
import pytest

from module.physical_power.PhysicalPowerAnalyse import (
    img_analyse,
    _extract_power_values,
    _extract_power_alternative,
)


def test_extract_power_values_standard_with_reserve():
    text = "开拓力 257/300 后备：2400"
    result = _extract_power_values(text, [])
    assert result["current_power"] == 257
    assert result["max_power"] == 300
    assert result["reserve_power"] == 2400


def test_extract_power_values_standard_no_reserve():
    text = "开拓力 80/240"
    result = _extract_power_values(text, [])
    assert result["current_power"] == 80
    assert result["max_power"] == 240
    assert result["reserve_power"] == 0


def test_extract_power_values_reserve_patterns():
    for text in ("后备开拓力：1234", "储备: 56", "开拓力储备：789"):
        result = _extract_power_values(text, [])
        if "1234" in text:
            assert result["reserve_power"] == 1234
        elif "56" in text:
            assert result["reserve_power"] == 56
        else:
            assert result["reserve_power"] == 789


def test_extract_power_values_no_text():
    result = _extract_power_values("", [])
    assert result == {"reserve_power": 0, "current_power": 0, "max_power": 0}


def test_extract_power_alternative_by_keyword():
    result = _extract_power_alternative(
        "当前体力 100/240",
        {"reserve_power": 0, "current_power": 0, "max_power": 0},
    )
    assert result["current_power"] == 100
    assert result["max_power"] == 240


def test_img_analyse_with_mocked_ocr(monkeypatch):
    from module.physical_power import PhysicalPowerAnalyse as ppa

    monkeypatch.setattr(ppa, "get_ocr_instance", lambda: None)
    monkeypatch.setattr(ppa, "_ocr_extract_text_with_position",
                        lambda ocr, path: ("开拓力 257/300 后备：2400", []))

    result = ppa.img_analyse(["fake_screenshot.png"])
    assert result == {"data": {"reserve_power": 2400, "current_power": 257, "max_power": 300}}


def test_img_analyse_empty_text(monkeypatch):
    from module.physical_power import PhysicalPowerAnalyse as ppa

    monkeypatch.setattr(ppa, "get_ocr_instance", lambda: None)
    monkeypatch.setattr(ppa, "_ocr_extract_text_with_position", lambda ocr, path: ("", []))

    assert ppa.img_analyse(["fake_screenshot.png"]) is None


def test_img_analyse_requires_path():
    from module.physical_power import PhysicalPowerAnalyse as ppa
    assert ppa.img_analyse([]) is None
    assert ppa.img_analyse(None) is None
