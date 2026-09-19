import time
from asyncio import timeout

from module.common.Locate import GetPosition
from pathlib import Path
import pyautogui
import module.interface.InterfaceManager as interface
from module.common.Capture import screen_capture as sc
from module.common.AutoOpen import StarRailGameManager
from utils.log.Log import Log
from module.physical_power.PhysicalPowerAnalyse import img_analyse as power_img_analyse

log = Log()
game = StarRailGameManager()

imag_path = Path(__file__).resolve().parent.parent.parent.joinpath("assets","images")
common_img_path = imag_path.joinpath("common")
daily_task_img_path = imag_path.joinpath("daily_task")

physical_power_img_path = imag_path.joinpath("physical_power")

calyx_img_path = physical_power_img_path.joinpath("calyx_golden")


pos = GetPosition()

def clear_physical_power(power_num:int=1,selection:int=3,use_reserve:bool=False):
    """
    :param power_num: 要清除的体力数值(默认全部清完)
    :param selection: 目标选择:1.信用点(默认) 2.角色经验 3.光维经验
    :param use_reserve:  是否使用开拓力（默认为False,若使用则为True)
    :return: None
    """
    wait_time = 0

    if game.is_game_running():
        game.switch_to_game()

    power_data = get_power_data()
    current_power =power_data['data']['current_power']
    reserve_power = power_data['data']['reserve_power']
    log.info(f"power_data:{power_data}")
    log.info(f"use_reserve:{use_reserve},power_num:{power_num}")
    #1.信用点
    if selection==1:
        img_path = calyx_img_path.joinpath("bud_of_treasures.png")
    #2.角色经验
    elif selection==2:
        img_path = calyx_img_path.joinpath("bud_of_memories.png")
    #3.光维经验
    elif selection == 3:
        img_path = calyx_img_path.joinpath("bud_of_aether.png")

    rest_num=0
    #1.不使用后备开拓力

    if not use_reserve:
        if current_power<10:
            return
        if power_num>24:
            rest_num=power_num-24
            power_num=24
        #清完全部体力
        log.info(f"power_num:{power_num}")
        if not power_num:
            if current_power>240:
                rest_num=(current_power-240)//10
                current_power=current_power-240

            cost_power(current_power//10,img_path)
            return

        #按照计划清除体力
        #剩余体力大于等于设定值，清除设定值
        if current_power//10>=power_num :
            cost_power(power_num, img_path)
        #否则清除剩余值
        else:
            cost_power(current_power//10,img_path)
        return

    #使用后备开拓力(若使用则加到300,如两者加起来都不够三百则都取出来)
    if reserve_power:
        if reserve_power+current_power<10:
            return

        number=0
        sum_power = current_power+reserve_power
        if sum_power<300:
            number=reserve_power
            # 如果使用后备开拓力，但不指定体力计划。按实际情况清除体力
            if not power_num:
                power_num=sum_power//10
            current_power = sum_power
        else:
            number = 300-current_power
            current_power=300
            if not power_num:
                power_num=30
        if number>0:
            use_rest_power(str(number))

        if power_num>24:
            rest_num=power_num-24
            power_num=24

        #默认只清除300体力
        if current_power //10 >= power_num:
            cost_power(power_num, img_path)
        else:
            cost_power(current_power // 10, img_path)
    if rest_num>0:
        clear_physical_power(rest_num,selection,False)
def cost_power(power_num, img_path:str, selection:int=3):
    if not interface.wait_until(physical_power_img_path.joinpath("survival_index.png")):
        print("当前不在生存索引界面")
        pyautogui.press("esc")
        return

    if interface.wait_until(calyx_img_path.joinpath("character_exit.png")):
        interface.wait_and_click(calyx_img_path.joinpath("calyx_golden_white.png"))
    else:
        interface.wait_and_click(calyx_img_path.joinpath("calyx_golden.png"))
    if not interface.wait_until(calyx_img_path.joinpath(img_path)):
        return
    x,y=interface.wait_until(calyx_img_path.joinpath(img_path))
    pyautogui.click(x + 368, y)

    actual_num=0
    if power_num>24:
        actual_num=24
    else:
        actual_num=power_num
    for i in range(actual_num-1):
        interface.wait_and_click(calyx_img_path.joinpath("add.png"),timeout=5)


    interface.wait_and_click(calyx_img_path.joinpath("challenge.png"))
    interface.wait_and_click(calyx_img_path.joinpath("start_challenge.png"))
    time.sleep(3)
    if interface.wait_until(calyx_img_path.joinpath("combat.png")):
        pyautogui.press("v",interval=1.5)
    pyautogui.press("b")
    # interface.wait_and_click(calyx_img_path.joinpath("combat.png"))
    # interface.wait_and_click(calyx_img_path.joinpath("quickly.png"))


    if interface.wait_until(calyx_img_path.joinpath("exit_level.png"),timeout=power_num*60):
        interface.wait_and_click(calyx_img_path.joinpath("exit_level.png"))
        time.sleep(3)
        # 返回主界面
        pyautogui.press("esc")
        log.info("press esc success")
    else:
        pyautogui.click()
        time.sleep(1.5)
        pyautogui.press("esc")

    if power_num-24>0:
        clear_physical_power(power_num-24, selection)

#使用后备开拓力
def use_rest_power(number:str):
    interface.wait_and_click(calyx_img_path.joinpath("reserve_power.png"))
    interface.wait_and_click(calyx_img_path.joinpath("get_reserve_power.png"))
    interface.wait_and_click(calyx_img_path.joinpath("how_much.png"))
    pyautogui.write(number)
    # interface.wait_and_click(calyx_img_path.joinpath("up_to_max.png"))
    interface.wait_and_click(calyx_img_path.joinpath("affirm.png"))
    interface.wait_until(calyx_img_path.joinpath("affirm.png"),timeout=1.5)
    pyautogui.press("esc")

 # 根据ocr识别获取体力数据
def get_power_data():
    if not interface.wait_until(imag_path.joinpath("common","in_main.png")):
        print("当前不在主界面")
        return

    pyautogui.press("f4")
    #切换到生存索引界面
    if not interface.wait_until(calyx_img_path.joinpath("guide3.png"),timeout=5):
        interface.wait_and_click(calyx_img_path.joinpath("enter_guide3.png"))

    # 根据ocr识别获取体力数据
    time.sleep(1)
    sc(common_img_path.joinpath("screenshot.png"))
    power_json = power_img_analyse([common_img_path.joinpath("screenshot.png")])
    return power_json

if __name__ == '__main__':

    clear_physical_power()


