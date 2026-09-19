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
# 同机部署：client 与 Mod 在同一台电脑时，两端自动用主机名对齐，可省略参数
python -m mods.starrail
# 跨机 / 自定义设备名：显式指定目标设备
python -m mods.starrail --target-client my-pc
python -m mods.starrail --target-client my-pc --user-id 123 --timeout 300
```

参数：
- `--target-client`：目标设备名（client 端注册的 deviceName），**缺省时自动回退**
  `SMTPLAY_DEVICE_NAME` 环境变量 → 本机主机名（与 client 端注册逻辑一致，同机部署两端自动对齐）；
  可省略并在指令中传 `params.target_client`，也可传完整标识 `client:{userId}:{deviceName}`
- `--user-id`：用户 ID，缺省时从 JWT 自动解析（`sub`/`userId`/`uid`/`id`/`user_id`）
- `--device-name`：Mod 自身注册名（默认 `starrail`）
- `--timeout`：单次驱动操作超时（秒，默认 3600；清体力/完整日常可达几十分钟，切勿设成 180 这类短值）

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
| `ping` | **Mod 级**连通性检查（不碰客户端，立即响应） | `{pong, mod}` |
| `driver/ping` | **驱动级**连通性检查（转发到 client，验证全链路） | 驱动 pong 信息 |
| `status` | 驱动状态 + 体力 | `{driver, power}` |
| `daily_task` | 完整日常流程（转发驱动 `daily_task/start`；完成后回查一次剩余任务） | `{started, remaining}` |
| `daily_task/observe` | 仅观察，返回未完成任务列表 | `{task_ids, supported}` |
| `daily_task/reward` | 仅领取每日实训奖励 | `{claimed}` |
| `power/query` | 查询开拓力 | 体力数据 |
| `clear_power` | 清理开拓力（体力校验在驱动侧；完成后回查一次当前体力） | `{cleared, power}` |

> `remaining` / `power` 为执行完成后的状态采集结果，供调用方（前端/脚本）刷新状态并决策下一步；
> 采集失败时为 `null`，不影响 `status: ok` 的主结果。

> **排查提示**：`ping` 超时 = 控制器→服务器→Mod 链路问题；`ping` 通但 `driver/ping` 超时 = client 不在线 / deviceName 不匹配 / client 忙。

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
python -m mods.starrail              # 同机部署可省略 --target-client
python -m mods.starrail.controller --operate status
python -m mods.starrail.controller --operate daily_task
python -m mods.starrail.controller --operate clear_power --param '{"power_num": 10}'
```
