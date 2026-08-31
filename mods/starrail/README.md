# StarRail Mod（崩坏：星穹铁道 逻辑端）

StarRailMod 是 SmartPlayBuddy 的 **Mod（逻辑端）** 节点，与设备端 **starrail 驱动**
（`src/smartplaybuddy/drivers/starrail/`）配合，形成完整的「日常任务 + 开拓力清理」自动化插件。

## 分工

| 端 | 职责 |
|----|------|
| **Driver**（client 设备端） | 游戏内原子操作：截图定位、点击、按键、OCR 识别、游戏启动/切换 |
| **Mod**（本目录，逻辑端） | 高层编排：观察任务 → 逐项执行 → 领奖；查询体力 → 安全校验 → 清理 |

## 架构

```
控制器 ──command(action="starrail")──▶ StarRailMod（本 Mod）
StarRailMod ──command(action="starrail")──▶ client:{userId}:{deviceName}（客户端）
客户端 starrail 驱动执行 ──response──▶ StarRailMod
StarRailMod ──response──▶ 控制器
```

## 运行

```bash
# 在项目根目录
python -m mods.starrail --target-client my-pc
python -m mods.starrail --target-client my-pc --user-id 123 --timeout 300
```

参数：
- `--target-client`：目标设备名（client 端注册的 deviceName），可省略并在指令中传 `params.target_client`
- `--user-id`：用户 ID，缺省时从 JWT 自动解析（`sub`/`userId`/`uid`/`id`/`user_id`）
- `--device-name`：Mod 自身注册名（默认 `starrail`）
- `--timeout`：单次驱动操作超时（秒，默认 180）

## 指令协议

控制器向 `mod:{userId}:starrail` 发送 `command`（`action="starrail"`），`data` 结构：

```json
{
  "operate": "daily_task | clear_power | status | ping | power/query | daily_task/reward",
  "params": {
    "power_num": 0,
    "selection": 3,
    "use_reserve": false,
    "target_client": "my-pc",
    "timeout": 300
  }
}
```

### 指令说明

| operate | 行为 | 响应 result |
|---------|------|-------------|
| `ping` | 检查驱动连通性 | 驱动 pong 信息 |
| `status` | 驱动状态 + 体力 | `{driver, power}` |
| `daily_task` | 观察 → 逐项执行 → 领奖 | `{observed, executed, claim}` |
| `daily_task/reward` | 仅领取每日实训奖励 | `{claimed}` |
| `power/query` | 查询开拓力 | 体力数据 |
| `clear_power` | 校验后清理开拓力 | `{power, cleared}` 或 `{skipped, current_power}` |

## 测试

### 单元测试 / 冒烟测试

```bash
python -m pytest tests/ -v
```

### 游戏内测试

见 [游戏内测试指南](../../docs/zh-CN/starrail-testing.md) —— 分四个阶段：
本地直测（无副作用操作）→ 单任务步骤 → 小规模体力清理 → 端到端控制器。

控制器用法（先启动客户端与 Mod）：

```bash
python -m mods.starrail --target-client my-pc
python -m mods.starrail.controller --operate status
python -m mods.starrail.controller --operate daily_task
python -m mods.starrail.controller --operate clear_power --param '{"power_num": 10}'
```
