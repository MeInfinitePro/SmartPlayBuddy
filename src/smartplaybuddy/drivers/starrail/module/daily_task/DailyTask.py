import time
import pyautogui
from pathlib import Path

from module.interface.InterfaceManager import interface_switch
from module.common.Locate import GetPosition
from module.common.Capture import screen_capture as sc
from module.daily_task.DailyTaskAnalyse import daily_task_analyse as task_analyse
import module.interface.InterfaceManager as interface


pos = GetPosition()

assets_path = Path(__file__).resolve().parent.parent.parent.joinpath("assets")
task_img_path=assets_path.joinpath("images","daily_task")

#领取委托派遣
def entrust():
    # 确保在主界面
    if not interface.wait_until(assets_path.joinpath("images","common","in_main.png"), timeout=5):
        print("❌ 未检测到主界面")
        return

    pyautogui.press('esc')

    interface.wait_until(task_img_path.joinpath("entrust.png"), timeout=5)  # 等待主菜单出现

    interface.wait_and_click(task_img_path.joinpath("entrust.png"))

    # 尝试领取奖励
    if interface.wait_until(task_img_path.joinpath("re_award.png"), timeout=3):
        interface.wait_and_click(task_img_path.joinpath("re_award.png"), timeout=3)
        time.sleep(0.5)  # 短暂等待动画
        pyautogui.click()
    else:
        print("委托派遣尚未完成或已领取")
        return

    # 退出委托界面
    interface.wait_and_click(task_img_path.joinpath("exit.png"))
    # 再退出到主界面
    interface.wait_and_click(task_img_path.joinpath("exit.png"), timeout=3)
#使用一次万能合成台
def once_mix():
    if not interface.wait_until(assets_path.joinpath("images","common","in_main.png"), timeout=5):
        print("❌ 未检测到主界面")
        return

    pyautogui.press('esc')
    interface.wait_until(task_img_path.joinpath("mix.png"), timeout=5)

    interface.wait_and_click(task_img_path.joinpath("mix.png"))
    interface.wait_and_click(task_img_path.joinpath("mix_button.png"))

    interface.wait_and_click(task_img_path.joinpath("affirm.png"),timeout=60)
    print("合成失败")

    # 等待合成完成（可等待成功标志，如"合成成功"图标）
    if interface.wait_until(task_img_path.joinpath("mix_success.png"), timeout=8):
        print("✅ 合成成功")
        interface.wait_and_click(task_img_path.joinpath("mix_success.png"), timeout=8)
    else:
        print("⚠️ 合成状态未知")

    interface.wait_and_click(task_img_path.joinpath("exit.png"))
    interface.wait_and_click(task_img_path.joinpath("exit.png"), timeout=3)
#完成一次拍照
def take_photo():
    if not interface.wait_until(assets_path.joinpath("images","common","in_main.png"), timeout=5):
        return

    pyautogui.press('esc')
    interface.wait_and_click(task_img_path.joinpath("camera.png"))

    # 等待相机界面加载
    if interface.wait_until(task_img_path.joinpath("camera_ui.png"), timeout=5):
        pyautogui.press('f')
        time.sleep(1)  # 拍照瞬间仍需短暂等待
        interface.wait_and_click(task_img_path.joinpath("exit.png"),timeout=3)
        time.sleep(1.5)
        pyautogui.click()
#领取每日实训奖励
def re_award():
    if not interface.wait_until(assets_path.joinpath("images","common","in_main.png"), timeout=5):
        return

    pyautogui.press("f4")
    #切换到每日实训界面
    interface_switch(1150,0)

    if interface.wait_until(task_img_path.joinpath("daily_task.png"), timeout=5):

        # 循环领取直到没有可领取的

        while True :
            if interface.wait_until(task_img_path.joinpath("dt_re_award.png"), timeout=1.5, interval=0.5):
                print("检测到有待领取的奖励")
                interface.wait_and_click(task_img_path.joinpath("dt_re_award.png"), timeout=1.5, interval=0.5)
                time.sleep(0.3)
            else:
                break

    if interface.wait_until(task_img_path.joinpath("re_gift.png"), timeout=3):
            interface.wait_and_click(task_img_path.joinpath("re_gift.png"), timeout=3)
            time.sleep(1)
            pyautogui.click()

    interface.wait_and_click(task_img_path.joinpath("exit.png"))
    print("每日实训任务完成")
#检测每日实训任务并执行
def observe_task():
    if not interface.wait_until(assets_path.joinpath("images","common","in_main.png"), timeout=5):
        return []
    pyautogui.press("f4")
    #切换到每日实训界面
    interface_switch(1150,0)

    shot1_path = assets_path.joinpath("images", "common", "shot1.png")
    shot2_path = assets_path.joinpath("images", "common", "shot2.png")
    # 截取任务列表
    sc(shot1_path)
    if pos.get_target_pos(target_path=task_img_path.joinpath("daily_task.png")) is None:
        print("每日任务识别失败")
        interface.wait_and_click(task_img_path.joinpath("exit.png"))
        return

    x,y=pos.get_target_pos(target_path=task_img_path.joinpath("daily_task.png"))
    for _ in range(3):
        mouse_move(x, y)
    time.sleep(5)
    sc(shot2_path)

    tasks = task_analyse(img_path=[str(shot1_path), str(shot2_path)])
    #返回到主界面
    interface.wait_and_click(task_img_path.joinpath("exit.png"))
    res = []
    if len(tasks)==0:
        return []
    for i in range(len(tasks)):
        res.append(tasks[i]["id"])
    return res
# 建立可能的日常任务id映射
daily_task_dict = {
    2:entrust,
    9:once_mix,
    10:take_photo,
}
#鼠标移动
def mouse_move(x,y):
    tx, ty = x +1200 , y + 500
    pyautogui.moveTo(tx, ty)
    pyautogui.dragTo(tx - 500, ty,duration=0.5,button='left')
#执行任务
def run_task(id:int):
    return daily_task_dict[id]()


def start_daily_task():

    if interface.wait_until(assets_path.joinpath("images","common","in_main.png"),timeout=2):
        tasks_ids = observe_task()
        if len(tasks_ids)==0:
            print("所有任务已完成")
            return
        try:
            for task_id in tasks_ids:
                if task_id in daily_task_dict:
                    print(f"检测到要执行的任务id:{task_id},name{daily_task_dict[task_id]}")
                    run_task(task_id)
            time.sleep(2)
            re_award()
        except Exception as e:
            print("执行任务出错，任务结束")

if __name__ == '__main__':
    # time.sleep(3)
    # game.auto_open()
    # game.auto_open()
    # game.login()
    time.sleep(3)
    start_daily_task()
    # interface.wait_and_click(task_img_path.joinpath("affirm.png"))
    # once_mix()
    # take_photo()
    # observe_task()
