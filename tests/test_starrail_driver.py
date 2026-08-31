"""StarRailDriver 单元测试：operate() 分发逻辑（游戏交互函数全部 mock）。"""
import pytest


def test_driver_is_basedriver_subclass(starrail_driver_module):
    from drivers.base import BaseDriver
    assert issubclass(starrail_driver_module.StarRailDriver, BaseDriver)
    assert starrail_driver_module.StarRailDriver.name == "starrail"


def test_driver_ping(starrail_driver_module):
    driver = starrail_driver_module.StarRailDriver()
    resp = driver.operate("starrail", {"operate": "ping"})
    assert resp["status"] == "ok"
    assert resp["result"]["pong"] is True
    assert resp["result"]["driver"] == "starrail"


def test_driver_unknown_command(starrail_driver_module):
    driver = starrail_driver_module.StarRailDriver()
    resp = driver.operate("mouse", {"operate": "ping"})
    assert resp["status"] == "error"
    assert "unsupported command" in resp["message"]


def test_driver_unknown_operate(starrail_driver_module):
    driver = starrail_driver_module.StarRailDriver()
    resp = driver.operate("starrail", {"operate": "no_such_op"})
    assert resp["status"] == "error"
    assert "unknown operate" in resp["message"]


def test_driver_observe(starrail_driver_module, monkeypatch):
    driver = starrail_driver_module.StarRailDriver()
    monkeypatch.setattr(starrail_driver_module, "observe_task", lambda: [2, 9, 10])
    resp = driver.operate("starrail", {"operate": "daily_task/observe"})
    assert resp["status"] == "ok"
    assert resp["result"]["task_ids"] == [2, 9, 10]


def test_driver_observe_none(starrail_driver_module, monkeypatch):
    driver = starrail_driver_module.StarRailDriver()
    monkeypatch.setattr(starrail_driver_module, "observe_task", lambda: None)
    resp = driver.operate("starrail", {"operate": "daily_task/observe"})
    assert resp["status"] == "ok"
    assert resp["result"]["task_ids"] == []


def test_driver_daily_task_start(starrail_driver_module, monkeypatch):
    driver = starrail_driver_module.StarRailDriver()
    calls = []
    monkeypatch.setattr(starrail_driver_module, "start_daily_task", lambda: calls.append("start"))
    resp = driver.operate("starrail", {"operate": "daily_task/start"})
    assert resp["status"] == "ok"
    assert calls == ["start"]


def test_driver_task_steps(starrail_driver_module, monkeypatch):
    driver = starrail_driver_module.StarRailDriver()
    calls = []
    monkeypatch.setattr(starrail_driver_module, "entrust", lambda: calls.append("entrust"))
    monkeypatch.setattr(starrail_driver_module, "once_mix", lambda: calls.append("mix"))
    monkeypatch.setattr(starrail_driver_module, "take_photo", lambda: calls.append("photo"))
    monkeypatch.setattr(starrail_driver_module, "re_award", lambda: calls.append("reward"))
    for op in ("daily_task/entrust", "daily_task/mix", "daily_task/photo", "daily_task/reward"):
        resp = driver.operate("starrail", {"operate": op})
        assert resp["status"] == "ok", op
    assert calls == ["entrust", "mix", "photo", "reward"]


def test_driver_power_query(starrail_driver_module, monkeypatch):
    driver = starrail_driver_module.StarRailDriver()
    power = {"data": {"reserve_power": 2400, "current_power": 257, "max_power": 300}}
    monkeypatch.setattr(starrail_driver_module, "get_power_data", lambda: power)
    resp = driver.operate("starrail", {"operate": "power/query"})
    assert resp["status"] == "ok"
    assert resp["result"] == power


def test_driver_power_clear_params(starrail_driver_module, monkeypatch):
    driver = starrail_driver_module.StarRailDriver()
    captured = {}

    def fake_clear(power_num=1, selection=3, use_reserve=False):
        captured.update(power_num=power_num, selection=selection, use_reserve=use_reserve)

    monkeypatch.setattr(starrail_driver_module, "clear_physical_power", fake_clear)
    resp = driver.operate("starrail", {
        "operate": "power/clear", "power_num": 24, "selection": 1, "use_reserve": True,
    })
    assert resp["status"] == "ok"
    assert captured == {"power_num": 24, "selection": 1, "use_reserve": True}
    assert resp["result"]["params"] == {"power_num": 24, "selection": 1, "use_reserve": True}


def test_driver_power_clear_defaults(starrail_driver_module, monkeypatch):
    driver = starrail_driver_module.StarRailDriver()
    captured = {}

    def fake_clear(power_num=1, selection=3, use_reserve=False):
        captured.update(power_num=power_num, selection=selection, use_reserve=use_reserve)

    monkeypatch.setattr(starrail_driver_module, "clear_physical_power", fake_clear)
    driver.operate("starrail", {"operate": "power/clear"})
    assert captured == {"power_num": 0, "selection": 3, "use_reserve": False}


def test_driver_status(starrail_driver_module, monkeypatch):
    driver = starrail_driver_module.StarRailDriver()
    monkeypatch.setattr(driver.game, "is_game_running", lambda: False)
    resp = driver.operate("starrail", {"operate": "status"})
    assert resp["status"] == "ok"
    assert resp["result"]["driver"] == "starrail"
    assert resp["result"]["game_running"] is False
    assert resp["result"]["modules"]["daily_task"] is True
    assert resp["result"]["modules"]["physical_power"] is True


def test_driver_game_ops(starrail_driver_module, monkeypatch):
    driver = starrail_driver_module.StarRailDriver()
    monkeypatch.setattr(driver.game, "is_game_running", lambda: True)
    monkeypatch.setattr(driver.game, "open_game", lambda wait_for_login=True: True)
    monkeypatch.setattr(driver.game, "switch_to_game", lambda force=False: True)
    monkeypatch.setattr(driver.game, "close_game", lambda: True)

    assert driver.operate("starrail", {"operate": "game/running"})["result"]["running"] is True
    assert driver.operate("starrail", {"operate": "game/open"})["result"]["opened"] is True
    assert driver.operate("starrail", {"operate": "game/switch"})["result"]["switched"] is True
    assert driver.operate("starrail", {"operate": "game/close"})["result"]["closed"] is True
