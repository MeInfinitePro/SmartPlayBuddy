# StarRail Driver（崩坏：星穹铁道 驱动插件）

本驱动将 [starrail_assistant](https://github.com/InfinitProgress/starrail_assistant) 的
**每日实训任务（daily_task）** 与 **开拓力清理（physical_power）** 功能整体迁移到
SmartPlayBuddy 驱动框架，并保留其原始项目结构：

```
drivers/starrail/
├── manifest.json          ← 驱动插件清单（appid/version/entry/actions）
├── driver.py              ← StarRailDriver（继承 BaseDriver）
├── requirements.txt       ← 依赖声明（首次加载自动安装到 packages/）
├── module/                ← 原 starrail_assistant/module（结构原样保留）
│   ├── common/            ←   截图 Capture / 定位 Locate / 启动游戏 AutoOpen / AIUtils
│   ├── daily_task/        ←   DailyTask（执行）+ DailyTaskAnalyse（OCR 分析）
│   ├── interface/         ←   InterfaceManager（wait_until / wait_and_click）
│   └── physical_power/    ←   PhysicalPower（清理）+ PhysicalPowerAnalyse（OCR 识别）
├── utils/log/             ← 原 starrail_assistant/utils/log（Log.py）
└── assets/                ← 原 starrail_assistant/assets（匹配图片 + JSON 配置）
```

## 依赖

在开发环境下依赖已随主环境安装；打包（PyInstaller）环境下由 DriverRegistry
首次调用时自动执行 `pip install --target packages/ -r requirements.txt`。

## 可用操作（operate）

| operate | 说明 |
|---------|------|
| `ping` | 驱动连通性检查 |
| `status` | 驱动状态 + 游戏是否运行 |
| `game/running` / `game/open` / `game/switch` / `game/close` | 游戏生命周期 |
| `daily_task/start` | 完整日常流程（观察 → 逐项执行 → 领奖，原始语义） |
| `daily_task/observe` | 观察并返回未完成任务 id 列表 |
| `daily_task/entrust` | 领取委托派遣奖励 |
| `daily_task/mix` | 使用一次万能合成台 |
| `daily_task/photo` | 完成一次拍照 |
| `daily_task/reward` | 领取每日实训奖励 |
| `power/query` | OCR 识别开拓力数据 |
| `power/clear` | 清理开拓力（`power_num`=0 全部清完，`selection`=1信用点/2角色经验/3光锥经验，`use_reserve` 是否用后备体力） |

## 本地调试

```bash
python src/smartplaybuddy/drivers/starrail/driver.py ping
python src/smartplaybuddy/drivers/starrail/driver.py status
```

## 与 Mod 配合

高阶编排（`daily_task` 全流程、`clear_power` 带安全校验的清理）由
[mods/starrail](../../../../../mods/starrail/README.md) 中的 `StarRailMod` 负责。
