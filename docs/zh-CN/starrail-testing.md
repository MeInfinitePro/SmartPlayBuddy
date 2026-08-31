# 游戏内测试指南（崩坏：星穹铁道 日常任务 / 开拓力）

本指南说明如何在游戏内验证迁移后的 **starrail 驱动 + Mod** 插件。
核心原则：**先跑无副作用操作，再跑单任务步骤，最后才测试消耗体力的流程。**

---

## 0. 测试前准备

1. **启动游戏**并登录到**主界面（主世界）**，确认进程名为 `StarRail.exe`（或 `崩坏星穹铁道.exe` / `HonkaiStarRail.exe`）。
2. **游戏窗口不要最小化 / 不要被遮挡**——所有操作依赖截取游戏窗口画面做模板匹配。
3. **分辨率建议 1920×1080 窗口化**（模板匹配图与坐标偏移按此设计，`AutoOpen.py` 的 `TARGET_WIDTH/HEIGHT` 即 1920×1080）。
4. **游戏界面语言为简体中文**——模板图和 OCR 关键词都是中文。
5. 确认依赖可导入（首次 OCR 会联网下载 RapidOCR 模型，需联网）：

```bash
python -c "import pyautogui, cv2, numpy, psutil, win32gui, PIL, rapidocr_onnxruntime; print('依赖 OK')"
```

6. 快速自检驱动本身能加载（不需要游戏）：

```bash
python src/smartplaybuddy/drivers/starrail/driver.py ping
```

---

## 1. 第一阶段：无副作用操作（先验证环境）

这些操作只截图、识别、切换界面，**不消耗任何资源**，适合作为第一轮验证。

```bash
# ① 确认驱动识别到游戏进程
python src/smartplaybuddy/drivers/starrail/driver.py status
#    → 期望 "game_running": true

# ② 截图 + OCR 读取开拓力（验证窗口截图 + OCR 链路）
python src/smartplaybuddy/drivers/starrail/driver.py power/query
#    → 期望返回 {"data": {"current_power": ..., "max_power": ..., "reserve_power": ...}}
#      注意此操作约需 3~5 秒（截图 + 模型加载）

# ③ 打开「每日实训」面板识别未完成任务（验证模板匹配 + 界面切换 + OCR）
python src/smartplaybuddy/drivers/starrail/driver.py daily_task/observe
#    → 期望返回 {"task_ids": [...]}，只含未完成的任务 id
#      （若返回 [] 且日志有"未检测到主界面"等，见"常见问题"）
```

**观察点**：主界面 → F4 打开星际和平指南 → 切换到每日实训页 → 截图 → 鼠标拖拽任务列表 → 二次截图 → OCR。全程约 10~20 秒，任何一步失败都会打印原因（如"等待超时: xxx.png"）。

## 2. 第二阶段：单个日常任务步骤（安全）

每项操作会**完成一个每日任务**，无副作用，可逐个验证：

```bash
# 领取委托派遣奖励（需要已完成委托）
python src/smartplaybuddy/drivers/starrail/driver.py daily_task/entrust

# 使用一次万能合成台
python src/smartplaybuddy/drivers/starrail/driver.py daily_task/mix

# 完成一次拍照
python src/smartplaybuddy/drivers/starrail/driver.py daily_task/photo

# 领取每日实训奖励
python src/smartplaybuddy/drivers/starrail/driver.py daily_task/reward
```

每项完成会打印 `"done": true`；如果某步骤没找到对应图标（如奖励已领取），会打印提示并返回。

## 3. 第三阶段：开拓力清理（⚠ 会消耗体力并进入战斗）

**先小规模测试，再放量。** `power_num` 单位是「次」，每次 = 10 体力 = 一场战斗。

```bash
# ① 只打 1 场（消耗 10 体力）验证完整链路：进入花萼 → 挑战 → 快速战斗 → 结算退出
python src/smartplaybuddy/drivers/starrail/driver.py power/clear '{"power_num": 10}'
#    → selection: 1=信用点 2=角色经验 3=光锥经验（默认 3）
#    → use_reserve: true 表示使用后备开拓力（需先有储备）

# ② 确认流程 OK 后再清更多（例如 120 体力 = 12 场，会分多轮进行）
python src/smartplaybuddy/drivers/starrail/driver.py power/clear '{"power_num": 120}'
```

> ⚠️ 注意：**不带参数直接运行 `power/clear` 等价于 power_num=0，会清空全部体力**（调试入口会打印警告）。
> 每场战斗最长等待 `power_num*60` 秒，请确保游戏窗口在前台可见。

## 4. 第四阶段：端到端（Client + Mod + 控制器）

完整链路：**控制器 → starrail Mod（编排）→ 客户端 starrail 驱动 → 游戏**。

### 4.1 启动客户端（游戏所在电脑）

```bash
smtplay        # 或 python -m smartplaybuddy.client
```

客户端会自动登录并注册为 `client:{userId}:{deviceName}`。默认 deviceName 为空（服务端分配 UUID），
**建议给客户端指定一个设备名**，方便 Mod 定位：编辑 `src/smartplaybuddy/client.py` 第 220 行附近，
把 `"deviceName": ""` 改为 `"deviceName": "my-pc"`。

### 4.2 启动星穹铁道 Mod

```bash
python -m mods.starrail --target-client my-pc
```

### 4.3 用控制器发指令（另开一个终端）

```bash
# 状态检查（驱动 + 体力）
python -m mods.starrail.controller --operate status

# 完整日常任务流程（观察 → 逐项执行 → 领奖）
python -m mods.starrail.controller --operate daily_task

# 安全地清理 10 体力
python -m mods.starrail.controller --operate clear_power --param '{"power_num": 10}'

# 指定目标设备（当 --target-client 未配置时）
python -m mods.starrail.controller --operate status --target-client my-pc
```

控制器会打印 Mod 的完整响应，如：

```json
{
  "type": "response",
  "data": {
    "status": "ok",
    "result": {
      "observed": [2, 9],
      "executed": [
        {"task_id": 2, "operate": "daily_task/entrust", "result": {"done": true, "op": "entrust"}},
        {"task_id": 9, "operate": "daily_task/mix", "result": {"done": true, "op": "mix"}}
      ],
      "claim": {"done": true, "op": "reward"}
    }
  }
}
```

---

## 5. 常见问题（FAQ）

| 现象 | 可能原因 | 处理 |
|------|----------|------|
| `status` 显示 `game_running: false` | 游戏未运行 / 进程名不同 | 确认游戏已启动，进程为 StarRail.exe |
| `等待超时: in_main.png` | 不在主界面 / 分辨率不符 / 窗口被遮挡 | 回到主世界；确认 1080p 窗口化且窗口可见 |
| 模板匹配失败（某 png 找不到） | 游戏版本/UI 主题与模板图不一致 | 重新截图替换 `assets/images/**` 对应模板图 |
| `power/query` 返回 null | 截图失败或 OCR 未识别到数字 | 确认窗口未被遮挡；首次运行等待模型下载完成 |
| `daily_task/observe` 返回 [] | 任务全部完成，或匹配失败 | 先看打印日志：若"未检测到主界面"则回到主世界 |
| 体力 < 10 时 `clear_power` 被跳过 | 安全校验（mod 编排层） | 属正常行为，`result.skipped` 为 true |
| 鼠标拖拽任务列表位置不对 | 窗口位置/分辨率与脚本假设不符 | 将游戏窗口置于主显示器，窗口化 1920×1080 |
| 战斗等待过久 | 结算画面模板匹配失败 | 检查 `exit_level.png` 模板；确认结算界面未被遮挡 |
| OCR 首次运行慢 | 模型下载 | 等待即可，之后有本地缓存 |
