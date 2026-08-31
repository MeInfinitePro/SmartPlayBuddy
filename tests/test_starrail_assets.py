"""插件资产 / 结构完整性测试（冒烟级）。"""
import json
from pathlib import Path


def test_manifest_valid(driver_plugin_dir):
    manifest_path = Path(driver_plugin_dir) / "manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for field in ("appid", "versionCode", "versionName", "name", "entry", "actions"):
        assert field in manifest, f"manifest 缺少字段: {field}"
    assert manifest["name"] == "starrail"
    assert manifest["entry"] == "driver.py"
    assert "starrail" in manifest["actions"]
    assert manifest["appid"].startswith("smartplaybuddy.driver.")


def test_requirements_declared(driver_plugin_dir):
    req = Path(driver_plugin_dir) / "requirements.txt"
    assert req.exists()
    content = req.read_text(encoding="utf-8")
    for dep in ("pyautogui", "opencv-python", "rapidocr-onnxruntime", "pywin32", "psutil", "pillow", "numpy"):
        assert dep in content, f"requirements 缺少依赖: {dep}"


def test_module_structure_preserved(driver_plugin_dir):
    """验证 starrail_assistant 的项目结构在驱动内原样保留。"""
    expected = [
        "module/common/Locate.py",
        "module/common/Capture.py",
        "module/common/AutoOpen.py",
        "module/common/AIUtils.py",
        "module/common/Test.py",
        "module/interface/InterfaceManager.py",
        "module/daily_task/DailyTask.py",
        "module/daily_task/DailyTaskAnalyse.py",
        "module/physical_power/PhysicalPower.py",
        "module/physical_power/PhysicalPowerAnalyse.py",
        "utils/log/Log.py",
    ]
    for rel in expected:
        assert (Path(driver_plugin_dir) / rel).exists(), f"缺失: {rel}"


def test_assets_images_present(driver_plugin_dir):
    base = Path(driver_plugin_dir) / "assets" / "images"
    common = base / "common"
    for name in ("in_main.png", "in_login.png", "interstellar_guide.png", "screenshot.png", "shot1.png", "shot2.png"):
        assert (common / name).exists(), f"缺失 common/{name}"

    daily = base / "daily_task"
    for name in ("entrust.png", "mix.png", "mix_button.png", "affirm.png", "camera.png",
                 "camera_ui.png", "exit.png", "dt_re_award.png", "re_gift.png",
                 "daily_task.png", "re_award.png", "mix_success.png"):
        assert (daily / name).exists(), f"缺失 daily_task/{name}"

    pp = base / "physical_power"
    assert (pp / "survival_index.png").exists(), "缺失 physical_power/survival_index.png"
    calyx = pp / "calyx_golden"
    for name in ("bud_of_treasures.png", "bud_of_memories.png", "bud_of_aether.png",
                 "add.png", "challenge.png", "start_challenge.png", "combat.png", "quickly.png",
                 "exit_level.png", "reserve_power.png", "get_reserve_power.png", "how_much.png",
                 "affirm.png", "calyx_golden.png", "calyx_golden_white.png", "character_exit.png"):
        assert (calyx / name).exists(), f"缺失 calyx_golden/{name}"


def test_json_configs_parse(driver_plugin_dir):
    json_dir = Path(driver_plugin_dir) / "assets" / "json"
    for name in ("daily_task.json", "locate.json", "power_format.json", "return_format.json", "starrail_config.json"):
        p = json_dir / name
        assert p.exists(), f"缺失 json/{name}"
        data = json.loads(p.read_text(encoding="utf-8"))
        assert data is not None

    daily = json.loads((json_dir / "daily_task.json").read_text(encoding="utf-8"))
    ids = {t["id"] for t in daily}
    # 驱动与 mod 支持的任务 id 必须存在于任务清单中
    assert {2, 9, 10} <= ids
